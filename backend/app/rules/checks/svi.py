"""R015 SVI shutdown or missing SVI.

Scoped deliberately so it does not restate what a mandatory rule already says:

* the **shutdown** sub-case only fires when the VLAN *does* exist in the database. When the
  VLAN is absent, R005 already reports the SVI that can never come up, and repeating it
  here would double-count one fault.
* the **missing SVI** sub-case only fires on a device that is actually doing inter-VLAN
  routing (a multilayer switch with ``ip routing`` enabled), because on a pure Layer 2
  switch having no SVI for a VLAN is normal, not a fault.

Both sub-cases additionally require hosts to be in the VLAN. A VLAN with no members has no
gateway to be missing.
"""

from __future__ import annotations

from backend.app.models.enums import (
    AdminState,
    ConceptTag,
    DeviceKind,
    OSILayer,
    Severity,
)
from backend.app.models.lab_state import Device
from backend.app.rules.engine import Finding, RuleContext, RuleEvidence, make_finding, rule


def _members(ctx: RuleContext, device: Device, vlan_id: int) -> list[str]:
    """Hosts attached to this device that sit in this VLAN."""
    return [
        host.name
        for host in ctx.state.hosts
        if host.vlan == vlan_id
        and host.connected_device
        and host.connected_device.lower() == device.name.lower()
    ]


@rule(
    id="R015",
    name="SVI shutdown or missing",
    category=ConceptTag.VLAN,
    severity=Severity.HIGH,
    osi_layer=OSILayer.L3,
    description=(
        "A VLAN that exists and has members has no usable gateway on the routing switch: "
        "its SVI is down, or no SVI was ever created for it."
    ),
    suggested_check="show ip interface brief  /  show running-config interface Vlan<id>",
)
def check_svi_state(ctx: RuleContext) -> list[Finding]:
    meta = check_svi_state.rule_meta  # type: ignore[attr-defined]
    findings: list[Finding] = []

    for device in ctx.state.devices:
        svi_vlans = {i.vlan for i in device.interfaces if i.is_svi and i.vlan is not None}

        # (a) The SVI exists and its VLAN exists, but the interface is down.
        for iface in device.interfaces:
            if not iface.is_svi or iface.vlan is None or not iface.is_down:
                continue
            if not device.has_vlan(iface.vlan):
                continue  # R005 owns the never-created-VLAN case.
            members = _members(ctx, device, iface.vlan)
            if not members:
                continue
            reason = (
                "administratively shut down"
                if iface.admin_state == AdminState.SHUTDOWN
                else "line-protocol down"
            )
            findings.append(
                make_finding(
                    meta,
                    severity=Severity.CRITICAL,
                    message=(
                        f"{device.name} {iface.name} is the gateway for VLAN {iface.vlan} but "
                        f"is {reason}, so {', '.join(members)} in that VLAN have no working "
                        "default gateway."
                    ),
                    evidence=[
                        RuleEvidence(
                            source=f"{device.name} / {iface.name}",
                            detail=(
                                f"admin_state={iface.admin_state.value} "
                                f"line_protocol={iface.oper_state.value}"
                                + (f" ip={iface.ip}" if iface.ip else "")
                            ),
                        ),
                        RuleEvidence(
                            source=f"{device.name} / vlan database",
                            detail=f"VLAN {iface.vlan} exists, members: {', '.join(members)}",
                        ),
                    ],
                    affected=[device.name, iface.name, f"VLAN{iface.vlan}"],
                    suggested_mutation=(
                        {
                            "type": "set_interface_admin_state",
                            "device": device.name,
                            "interface": iface.name,
                            "admin_state": AdminState.UP.value,
                        }
                        if iface.admin_state == AdminState.SHUTDOWN
                        else None
                    ),
                )
            )

        # (b) No SVI at all for a populated VLAN on a switch that routes between VLANs.
        if device.kind != DeviceKind.MULTILAYER_SWITCH or not device.ip_routing_enabled:
            continue
        for vlan in sorted(device.vlans, key=lambda v: v.vlan_id):
            if vlan.vlan_id in svi_vlans:
                continue
            members = _members(ctx, device, vlan.vlan_id)
            if not members:
                continue
            findings.append(
                make_finding(
                    meta,
                    message=(
                        f"{device.name} routes between VLANs but has no SVI for VLAN "
                        f"{vlan.vlan_id} ({vlan.name}), so {', '.join(members)} have no "
                        "gateway on that switch and cannot leave their own subnet."
                    ),
                    evidence=[
                        RuleEvidence(
                            source=f"{device.name} / vlan database",
                            detail=f"VLAN {vlan.vlan_id} ({vlan.name}) is active",
                        ),
                        RuleEvidence(
                            source=f"{device.name} / interfaces",
                            detail=(
                                "SVIs configured: "
                                + (
                                    ", ".join(f"Vlan{v}" for v in sorted(svi_vlans))
                                    or "none"
                                )
                            ),
                        ),
                    ],
                    affected=[device.name, f"VLAN{vlan.vlan_id}", *members],
                )
            )

    return findings
