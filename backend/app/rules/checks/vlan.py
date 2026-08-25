"""R005 missing VLAN — a mandatory check from the company document.

Three sub-cases, all of which present as "the PC is in the right VLAN but nothing works":

* a host sits in a VLAN that is absent from its access switch's VLAN database;
* an access port is assigned to a VLAN that does not exist on that switch;
* an SVI exists for a VLAN that was never created — the classic Packet Tracer trap where
  ``interface Vlan30`` is configured but ``vlan 30`` was never added, leaving the SVI
  permanently down.
"""

from __future__ import annotations

from backend.app.models.enums import ConceptTag, OSILayer, Severity, SwitchportMode
from backend.app.rules.engine import Finding, RuleContext, RuleEvidence, make_finding, rule


@rule(
    id="R005",
    name="Missing VLAN",
    category=ConceptTag.VLAN,
    severity=Severity.HIGH,
    osi_layer=OSILayer.L2,
    description=(
        "A VLAN is referenced by a host, an access port, or an SVI but does not exist in "
        "the switch's VLAN database."
    ),
    mandatory=True,
    suggested_check="show vlan brief",
)
def check_missing_vlan(ctx: RuleContext) -> list[Finding]:
    meta = check_missing_vlan.rule_meta  # type: ignore[attr-defined]
    findings: list[Finding] = []

    # (a) A host assigned to a VLAN its own switch does not know about.
    for host in ctx.state.hosts:
        if host.vlan is None or not host.connected_device:
            continue
        switch = ctx.state.device(host.connected_device)
        if switch is None or switch.has_vlan(host.vlan):
            continue
        findings.append(
            make_finding(
                meta,
                message=(
                    f"Host {host.name} is in VLAN {host.vlan}, but VLAN {host.vlan} does not "
                    f"exist in the VLAN database on {switch.name}."
                ),
                evidence=[
                    RuleEvidence(
                        source=host.name,
                        detail=f"assigned to VLAN {host.vlan} via {switch.name}",
                    ),
                    RuleEvidence(
                        source=f"{switch.name} / vlan database",
                        detail=_vlan_list(switch),
                    ),
                ],
                affected=[host.name, switch.name, f"VLAN{host.vlan}"],
                suggested_mutation={
                    "type": "add_vlan",
                    "device": switch.name,
                    "vlan_id": host.vlan,
                    "name": f"VLAN{host.vlan}",
                },
            )
        )

    # (b) An access port pointed at a non-existent VLAN.
    for device in ctx.state.devices:
        for iface in device.interfaces:
            if iface.switchport_mode != SwitchportMode.ACCESS or iface.vlan is None:
                continue
            if device.has_vlan(iface.vlan):
                continue
            findings.append(
                make_finding(
                    meta,
                    message=(
                        f"{device.name} {iface.name} is an access port in VLAN {iface.vlan}, "
                        f"but VLAN {iface.vlan} does not exist in the VLAN database on "
                        f"{device.name}."
                    ),
                    evidence=[
                        RuleEvidence(
                            source=f"{device.name} / {iface.name}",
                            detail=f"switchport access vlan {iface.vlan}",
                        ),
                        RuleEvidence(
                            source=f"{device.name} / vlan database",
                            detail=_vlan_list(device),
                        ),
                    ],
                    affected=[device.name, iface.name, f"VLAN{iface.vlan}"],
                    suggested_mutation={
                        "type": "add_vlan",
                        "device": device.name,
                        "vlan_id": iface.vlan,
                        "name": f"VLAN{iface.vlan}",
                    },
                )
            )

    # (c) An SVI for a VLAN that was never created.
    for device in ctx.state.devices:
        for iface in device.interfaces:
            if not iface.is_svi or iface.vlan is None:
                continue
            if device.has_vlan(iface.vlan):
                continue
            findings.append(
                make_finding(
                    meta,
                    severity=Severity.CRITICAL,
                    message=(
                        f"{device.name} has SVI {iface.name} for VLAN {iface.vlan}, but VLAN "
                        f"{iface.vlan} was never created in the VLAN database. The SVI can "
                        "never come up, so that subnet has no gateway."
                    ),
                    evidence=[
                        RuleEvidence(
                            source=f"{device.name} / {iface.name}",
                            detail=(
                                f"SVI for VLAN {iface.vlan}"
                                + (f", ip address {iface.ip} {iface.mask}" if iface.ip else "")
                            ),
                        ),
                        RuleEvidence(
                            source=f"{device.name} / vlan database",
                            detail=_vlan_list(device),
                        ),
                    ],
                    affected=[device.name, iface.name, f"VLAN{iface.vlan}"],
                    suggested_mutation={
                        "type": "add_vlan",
                        "device": device.name,
                        "vlan_id": iface.vlan,
                        "name": f"VLAN{iface.vlan}",
                    },
                )
            )

    return findings


def _vlan_list(device) -> str:
    if not device.vlans:
        return "VLAN database is empty"
    return "VLANs present: " + ", ".join(
        f"{v.vlan_id} ({v.name})" for v in sorted(device.vlans, key=lambda v: v.vlan_id)
    )
