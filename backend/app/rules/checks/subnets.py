"""R009 overlapping subnets.

Two Layer 3 interfaces whose address space overlaps make the routing table ambiguous: one
subnet's traffic follows the other's connected route and never arrives. The usual cause is
a mask typo on a newly added VLAN, which is why this is checked structurally rather than
from any declared intent — an overlap is a fault whatever the network is meant to do.

The one legitimate case of two interfaces sharing a network is a point-to-point link
between them, so directly connected interfaces in the *same* network are not reported.
A partial overlap (one network containing the other) is always reported.
"""

from __future__ import annotations

from backend.app.models.enums import ConceptTag, OSILayer, Severity
from backend.app.models.lab_state import LabState
from backend.app.netutils import network_of
from backend.app.rules.engine import Finding, RuleContext, RuleEvidence, make_finding, rule


def _directly_connected(state: LabState, a: tuple[str, str], b: tuple[str, str]) -> bool:
    """Whether these two (device, interface) pairs are the two ends of one link."""
    for link in state.links:
        ends = {
            (link.a_device.lower(), link.a_interface.lower()),
            (link.b_device.lower(), link.b_interface.lower()),
        }
        if a in ends and b in ends:
            return True
    return False


@rule(
    id="R009",
    name="Overlapping subnets",
    category=ConceptTag.ROUTING,
    severity=Severity.HIGH,
    osi_layer=OSILayer.L3,
    description=(
        "Two Layer 3 interfaces are configured with overlapping address space, so one "
        "subnet's connected route swallows traffic destined for the other."
    ),
    suggested_check="show ip route  /  show ip interface brief",
)
def check_overlapping_subnets(ctx: RuleContext) -> list[Finding]:
    meta = check_overlapping_subnets.rule_meta  # type: ignore[attr-defined]

    entries = []
    for device, iface in ctx.state.l3_interfaces():
        net = network_of(iface.ip, iface.mask)
        if net is None:
            continue  # R002 reports a malformed mask.
        entries.append((device.name, iface.name, iface.ip, iface.mask, net))

    findings: list[Finding] = []
    for index, (dev_a, if_a, ip_a, mask_a, net_a) in enumerate(entries):
        for dev_b, if_b, ip_b, mask_b, net_b in entries[index + 1 :]:
            if not net_a.overlaps(net_b):
                continue
            identical = net_a == net_b
            if identical and _directly_connected(
                ctx.state, (dev_a.lower(), if_a.lower()), (dev_b.lower(), if_b.lower())
            ):
                continue  # A point-to-point link legitimately shares one network.

            relation = (
                f"both are configured in {net_a}"
                if identical
                else f"{net_a} and {net_b} overlap"
            )
            findings.append(
                make_finding(
                    meta,
                    severity=Severity.CRITICAL if not identical else Severity.HIGH,
                    message=(
                        f"{dev_a} {if_a} and {dev_b} {if_b} have overlapping address space: "
                        f"{relation}. The two subnets cannot both be reached."
                    ),
                    evidence=[
                        RuleEvidence(
                            source=f"{dev_a} / {if_a}",
                            detail=f"ip address {ip_a} {mask_a} (network {net_a})",
                        ),
                        RuleEvidence(
                            source=f"{dev_b} / {if_b}",
                            detail=f"ip address {ip_b} {mask_b} (network {net_b})",
                        ),
                    ],
                    affected=sorted({dev_a, dev_b}) + [if_a, if_b],
                )
            )

    return findings
