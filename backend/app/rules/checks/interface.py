"""R004 interface down — a mandatory check from the company document.

Only reports interfaces that *matter*: an unused, unconnected port being down is normal
housekeeping, not a fault. An interface is considered significant when it carries an IP,
is an SVI, or appears in a topology link.
"""

from __future__ import annotations

from backend.app.models.enums import AdminState, ConceptTag, OSILayer, Severity
from backend.app.models.lab_state import Device, Interface
from backend.app.rules.engine import Finding, RuleContext, RuleEvidence, make_finding, rule


@rule(
    id="R004",
    name="Interface down",
    category=ConceptTag.INTERFACE_CONFIG,
    severity=Severity.HIGH,
    osi_layer=OSILayer.L1,
    description=(
        "A significant interface is administratively shut down, or its line protocol is "
        "down. Significant means it carries an IP, is an SVI, or is part of a link."
    ),
    mandatory=True,
    suggested_check="show ip interface brief  /  show interfaces status",
)
def check_interface_down(ctx: RuleContext) -> list[Finding]:
    meta = check_interface_down.rule_meta  # type: ignore[attr-defined]
    findings: list[Finding] = []

    linked = _linked_interfaces(ctx)

    for device in ctx.state.devices:
        for iface in device.interfaces:
            if not iface.is_down:
                continue
            if not _is_significant(device, iface, linked):
                continue

            admin_down = iface.admin_state == AdminState.SHUTDOWN
            reason = (
                "administratively down (shutdown is configured)"
                if admin_down
                else "down/down (line protocol is down)"
            )
            subnet_note = (
                f", so subnet {iface.ip}/{iface.mask} is unreachable." if iface.ip else "."
            )
            findings.append(
                make_finding(
                    meta,
                    severity=_severity_for(iface),
                    message=f"{device.name} {iface.name} is {reason}{subnet_note}",
                    evidence=[
                        RuleEvidence(
                            source=f"{device.name} / {iface.name}",
                            detail=(
                                f"admin_state={iface.admin_state.value} "
                                f"line_protocol={iface.oper_state.value}"
                                + (f" ip={iface.ip}" if iface.ip else "")
                            ),
                        )
                    ],
                    affected=[device.name, iface.name],
                    suggested_mutation=(
                        {
                            "type": "set_interface_admin_state",
                            "device": device.name,
                            "interface": iface.name,
                            "admin_state": AdminState.UP.value,
                        }
                        if admin_down
                        else None
                    ),
                )
            )

    return findings


def _linked_interfaces(ctx: RuleContext) -> set[tuple[str, str]]:
    """(device, interface) pairs that appear in at least one link, lower-cased."""
    pairs: set[tuple[str, str]] = set()
    for link in ctx.state.links:
        pairs.add((link.a_device.lower(), link.a_interface.lower()))
        pairs.add((link.b_device.lower(), link.b_interface.lower()))
    return pairs


def _is_significant(device: Device, iface: Interface, linked: set[tuple[str, str]]) -> bool:
    if iface.ip or iface.is_svi:
        return True
    return (device.name.lower(), iface.name.lower()) in linked


def _severity_for(iface: Interface) -> Severity:
    """A down interface that terminates a subnet is worse than a down access port."""
    if iface.ip or iface.is_svi:
        return Severity.CRITICAL
    return Severity.HIGH
