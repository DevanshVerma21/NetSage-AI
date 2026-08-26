"""R007 access VLAN mismatch and R008 trunk / native VLAN mismatch.

Both are optional Phase 5 rules: they are not among the six the company document names,
so they are deliberately **not** marked ``mandatory``.

Both read the declared topology rather than guessing. A :class:`Link` carries the VLAN the
cabling plan says that segment belongs to (``access_vlan``, ``allowed_vlans``,
``native_vlan``), and the interfaces carry what is actually configured. A mismatch between
the two is a deterministic fault, not a matter of taste — which is what keeps these rules
from firing merely because a configuration looks unusual.
"""

from __future__ import annotations

from typing import Optional

from backend.app.models.enums import ConceptTag, LinkMode, OSILayer, Severity, SwitchportMode
from backend.app.models.lab_state import Device, Interface, Link
from backend.app.rules.engine import Finding, RuleContext, RuleEvidence, make_finding, rule


def _endpoints(ctx: RuleContext, link: Link) -> list[tuple[Device, Interface]]:
    """The (device, interface) pairs of a link that exist as configured devices."""
    pairs: list[tuple[Device, Interface]] = []
    for name, if_name in ((link.a_device, link.a_interface), (link.b_device, link.b_interface)):
        device = ctx.state.device(name)
        if device is None:
            continue
        iface = device.interface(if_name)
        if iface is not None:
            pairs.append((device, iface))
    return pairs


def _segment(link: Link) -> str:
    return (
        f"{link.a_device} {link.a_interface} <-> {link.b_device} {link.b_interface}"
    )


@rule(
    id="R007",
    name="Access VLAN mismatch",
    category=ConceptTag.VLAN,
    severity=Severity.HIGH,
    osi_layer=OSILayer.L2,
    description=(
        "An access port is configured in a different VLAN from the one the segment "
        "belongs to, or the host attached to it is a member of a different VLAN. The port "
        "comes up, so the fault looks like a routing problem from the client."
    ),
    suggested_check="show interfaces status  /  show interfaces <if> switchport",
)
def check_access_vlan_mismatch(ctx: RuleContext) -> list[Finding]:
    meta = check_access_vlan_mismatch.rule_meta  # type: ignore[attr-defined]
    findings: list[Finding] = []

    for link in ctx.state.links:
        if link.mode != LinkMode.ACCESS or link.access_vlan is None:
            continue

        for device, iface in _endpoints(ctx, link):
            if iface.switchport_mode != SwitchportMode.ACCESS or iface.vlan is None:
                continue
            if iface.vlan == link.access_vlan:
                continue
            findings.append(
                make_finding(
                    meta,
                    message=(
                        f"{device.name} {iface.name} is configured as an access port in "
                        f"VLAN {iface.vlan}, but the segment it serves belongs to VLAN "
                        f"{link.access_vlan}. Traffic from that port lands in the wrong "
                        "broadcast domain."
                    ),
                    evidence=[
                        RuleEvidence(
                            source=f"{device.name} / {iface.name}",
                            detail=f"switchport access vlan {iface.vlan}",
                        ),
                        RuleEvidence(
                            source="topology / segment",
                            detail=f"{_segment(link)} is VLAN {link.access_vlan}",
                        ),
                    ],
                    affected=[device.name, iface.name, f"VLAN{iface.vlan}"],
                )
            )

        for name in (link.a_device, link.b_device):
            host = ctx.state.host(name)
            if host is None or host.vlan is None or host.vlan == link.access_vlan:
                continue
            findings.append(
                make_finding(
                    meta,
                    message=(
                        f"Host {host.name} is a member of VLAN {host.vlan} but is cabled to "
                        f"a segment in VLAN {link.access_vlan}, so it is placed in the wrong "
                        "subnet's broadcast domain."
                    ),
                    evidence=[
                        RuleEvidence(
                            source=host.name,
                            detail=(
                                f"VLAN {host.vlan}, attached to {host.connected_device} "
                                f"{host.connected_interface}"
                            ),
                        ),
                        RuleEvidence(
                            source="topology / segment",
                            detail=f"{_segment(link)} is VLAN {link.access_vlan}",
                        ),
                    ],
                    affected=[host.name, f"VLAN{host.vlan}"],
                )
            )

    return findings


@rule(
    id="R008",
    name="Trunk or native VLAN mismatch",
    category=ConceptTag.VLAN,
    severity=Severity.HIGH,
    osi_layer=OSILayer.L2,
    description=(
        "A trunk does not carry a VLAN the segment is supposed to carry, or the two ends "
        "of the trunk disagree about the native VLAN. Both leave some VLANs working and "
        "others silently black-holed across the same cable."
    ),
    suggested_check="show interfaces trunk  /  show interfaces <if> switchport",
)
def check_trunk_vlan_mismatch(ctx: RuleContext) -> list[Finding]:
    meta = check_trunk_vlan_mismatch.rule_meta  # type: ignore[attr-defined]
    findings: list[Finding] = []

    for link in ctx.state.links:
        if link.mode != LinkMode.TRUNK:
            continue
        pairs = _endpoints(ctx, link)

        # (a) A VLAN the segment must carry that an end does not allow (trunk pruning).
        for vlan_id in link.allowed_vlans:
            for device, iface in pairs:
                if not iface.allowed_vlans or vlan_id in iface.allowed_vlans:
                    continue
                findings.append(
                    make_finding(
                        meta,
                        message=(
                            f"{device.name} {iface.name} is a trunk that does not carry VLAN "
                            f"{vlan_id}, but the segment {_segment(link)} is required to "
                            f"carry it. VLAN {vlan_id} is pruned on this trunk."
                        ),
                        evidence=[
                            RuleEvidence(
                                source=f"{device.name} / {iface.name}",
                                detail=(
                                    "switchport trunk allowed vlan "
                                    + ",".join(str(v) for v in sorted(iface.allowed_vlans))
                                ),
                            ),
                            RuleEvidence(
                                source="topology / segment",
                                detail=(
                                    "segment must carry VLANs "
                                    + ",".join(str(v) for v in sorted(link.allowed_vlans))
                                ),
                            ),
                        ],
                        affected=[device.name, iface.name, f"VLAN{vlan_id}"],
                    )
                )

        # (b) The two ends disagree about the native VLAN. When the segment declares one,
        # each end is compared against it; otherwise the ends are compared with each other.
        natives = [(device, iface, iface.native_vlan) for device, iface in pairs]
        if link.native_vlan is not None:
            for device, iface, native in natives:
                if native is None or native == link.native_vlan:
                    continue
                findings.append(_native_finding(meta, link, device, iface, native, link.native_vlan))
        elif len(natives) == 2:
            (dev_a, if_a, native_a), (dev_b, if_b, native_b) = natives
            if native_a is not None and native_b is not None and native_a != native_b:
                findings.append(
                    _native_finding(meta, link, dev_a, if_a, native_a, native_b, peer=dev_b.name)
                )

    return findings


def _native_finding(
    meta,
    link: Link,
    device: Device,
    iface: Interface,
    native: int,
    expected: int,
    peer: Optional[str] = None,
) -> Finding:
    """One end of a trunk carries the wrong native VLAN.

    Untagged frames are accepted into whichever VLAN each end calls native, so the two
    ends leak traffic between VLANs and STP complains — a fault a human must see stated
    against the *other* end, not in isolation.
    """
    against = f"the far end ({peer})" if peer else "the segment"
    return make_finding(
        meta,
        message=(
            f"{device.name} {iface.name} uses native VLAN {native} on trunk "
            f"{_segment(link)}, but {against} uses native VLAN {expected}. Untagged frames "
            "cross between the two VLANs."
        ),
        evidence=[
            RuleEvidence(
                source=f"{device.name} / {iface.name}",
                detail=f"switchport trunk native vlan {native}",
            ),
            RuleEvidence(
                source="topology / segment" if peer is None else f"{peer} / far end",
                detail=f"native VLAN {expected}",
            ),
        ],
        affected=[device.name, iface.name, f"VLAN{native}"],
    )
