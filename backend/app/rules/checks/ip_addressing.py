"""R001 duplicate IP addresses and R002 wrong subnet masks.

Both are mandatory checks named in the company document.
"""

from __future__ import annotations

from collections import defaultdict

from backend.app.models.enums import ConceptTag, OSILayer, Severity
from backend.app.netutils import is_valid_netmask, mask_to_prefix
from backend.app.rules.engine import Finding, RuleContext, RuleEvidence, make_finding, rule


@rule(
    id="R001",
    name="Duplicate IP address",
    category=ConceptTag.GATEWAY,
    severity=Severity.CRITICAL,
    osi_layer=OSILayer.L3,
    description=(
        "The same IPv4 address is configured on more than one interface or host. "
        "Causes intermittent reachability as ARP entries flap between the two owners."
    ),
    mandatory=True,
    suggested_check="show ip arp  /  show ip interface brief",
)
def check_duplicate_ip(ctx: RuleContext) -> list[Finding]:
    """Flag any address claimed by two or more owners.

    Scope note: this compares addresses globally. Overlapping address space in separate
    VRFs would be legitimate, but the prototype's lab topologies have no VRFs, so an
    exact duplicate is always a fault here.
    """
    meta = check_duplicate_ip.rule_meta  # type: ignore[attr-defined]
    owners: dict[str, list[str]] = defaultdict(list)

    for device in ctx.state.devices:
        for iface in device.interfaces:
            if iface.ip:
                owners[iface.ip].append(f"{device.name} {iface.name}")

    for host in ctx.state.hosts:
        if host.ip:
            owners[host.ip].append(host.name)

    findings: list[Finding] = []
    for ip, claimants in sorted(owners.items()):
        if len(claimants) < 2:
            continue
        findings.append(
            make_finding(
                meta,
                message=(
                    f"IP address {ip} is configured on {len(claimants)} owners: "
                    f"{', '.join(claimants)}."
                ),
                evidence=[
                    RuleEvidence(source=claimant, detail=f"configured with {ip}")
                    for claimant in claimants
                ],
                affected=claimants,
                suggested_mutation={
                    "type": "resolve_duplicate_ip",
                    "ip": ip,
                    "keep": claimants[0],
                    "reassign": claimants[1:],
                },
            )
        )
    return findings


@rule(
    id="R002",
    name="Wrong subnet mask",
    category=ConceptTag.GATEWAY,
    severity=Severity.HIGH,
    osi_layer=OSILayer.L3,
    description=(
        "An invalid (non-contiguous) netmask, or a host whose mask disagrees with the "
        "mask on its own gateway's interface. Both break local/remote decisions."
    ),
    mandatory=True,
    suggested_check="show ip interface brief  /  show running-config interface <if>",
)
def check_wrong_subnet_mask(ctx: RuleContext) -> list[Finding]:
    """Three distinct mask faults, reported separately so the fix is unambiguous."""
    meta = check_wrong_subnet_mask.rule_meta  # type: ignore[attr-defined]
    findings: list[Finding] = []

    # (a) Structurally invalid masks — e.g. 255.255.0.255, a real Packet Tracer typo.
    for device in ctx.state.devices:
        for iface in device.interfaces:
            if iface.mask and not is_valid_netmask(iface.mask):
                findings.append(
                    make_finding(
                        meta,
                        severity=Severity.CRITICAL,
                        message=(
                            f"{device.name} {iface.name} has an invalid, non-contiguous "
                            f"subnet mask {iface.mask}."
                        ),
                        evidence=[
                            RuleEvidence(
                                source=f"{device.name} / {iface.name}",
                                detail=f"ip address {iface.ip} {iface.mask}",
                            )
                        ],
                        affected=[device.name, iface.name],
                    )
                )

    for host in ctx.state.hosts:
        if host.mask and not is_valid_netmask(host.mask):
            findings.append(
                make_finding(
                    meta,
                    severity=Severity.CRITICAL,
                    message=(
                        f"Host {host.name} has an invalid, non-contiguous subnet mask "
                        f"{host.mask}."
                    ),
                    evidence=[
                        RuleEvidence(
                            source=host.name,
                            detail=f"address {host.ip} mask {host.mask}",
                        )
                    ],
                    affected=[host.name],
                )
            )

    # (b) Host mask disagrees with the mask on the interface that owns its gateway.
    for host in ctx.state.hosts:
        if not (host.gateway and host.mask and is_valid_netmask(host.mask)):
            continue
        owner = ctx.state.owner_of_ip(host.gateway)
        if owner is None:
            continue  # R003 reports an unowned gateway; not a mask fault.
        device, iface = owner
        if not (iface.mask and is_valid_netmask(iface.mask)):
            continue
        if iface.mask == host.mask:
            continue
        findings.append(
            make_finding(
                meta,
                message=(
                    f"Host {host.name} uses mask {host.mask} (/{mask_to_prefix(host.mask)}) "
                    f"but its gateway {host.gateway} on {device.name} {iface.name} uses "
                    f"{iface.mask} (/{mask_to_prefix(iface.mask)}). The two disagree about "
                    "the size of the subnet."
                ),
                evidence=[
                    RuleEvidence(
                        source=host.name,
                        detail=f"address {host.ip} mask {host.mask} gateway {host.gateway}",
                    ),
                    RuleEvidence(
                        source=f"{device.name} / {iface.name}",
                        detail=f"ip address {iface.ip} {iface.mask}",
                    ),
                ],
                affected=[host.name, device.name, iface.name],
                suggested_mutation={
                    "type": "set_host_mask",
                    "host": host.name,
                    "mask": iface.mask,
                },
            )
        )

    # (c) A prefix too long to hold a host plus a gateway.
    for host in ctx.state.hosts:
        if not (host.ip and host.mask and host.gateway and is_valid_netmask(host.mask)):
            continue
        prefix = mask_to_prefix(host.mask)
        if prefix is not None and prefix >= 31:
            findings.append(
                make_finding(
                    meta,
                    message=(
                        f"Host {host.name} is configured with /{prefix} ({host.mask}), which "
                        "cannot accommodate both the host and its default gateway on a LAN."
                    ),
                    evidence=[
                        RuleEvidence(
                            source=host.name,
                            detail=f"address {host.ip} mask {host.mask} gateway {host.gateway}",
                        )
                    ],
                    affected=[host.name],
                )
            )

    return findings
