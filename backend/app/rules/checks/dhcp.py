"""R010 DHCP configuration fault.

Everything here is checked against the structured pool configuration and the segment the
pool is supposed to serve, never against ``show`` text. Five distinct faults share the rule
id because they all present to the user as "my PC has the wrong address, or no address":

* the pool's network does not match any subnet the serving device is attached to;
* the pool hands out a default gateway that is outside that subnet, or that nothing owns;
* an excluded address does not belong to the pool's network at all;
* a client is set to DHCP but no pool anywhere serves its segment and no relay is set;
* the pool hands out a DNS server address that no device or host in the topology owns.
"""

from __future__ import annotations

from typing import Optional

from backend.app.models.enums import ConceptTag, OSILayer, Severity
from backend.app.models.lab_state import Device, DhcpPool, Interface, LabState
from backend.app.netutils import ip_in_network, is_valid_netmask, network_of
from backend.app.rules.engine import Finding, RuleContext, RuleEvidence, make_finding, rule

_CHECK = "show ip dhcp pool  /  show running-config | section dhcp"


def _pool_label(device: Device, pool: DhcpPool) -> str:
    return f"{device.name} / dhcp pool {pool.name}"


def _segment_interface(state: LabState, host) -> Optional[tuple[Device, Interface]]:
    """The Layer 3 interface that serves the segment this client sits on.

    Located by VLAN membership first (a client with no lease has no address to match on)
    and by subnet second.
    """
    device = state.device(host.connected_device) if host.connected_device else None
    if device is not None and host.vlan is not None:
        for iface in device.interfaces:
            if iface.ip and iface.vlan == host.vlan:
                return device, iface
    if host.ip:
        for dev, iface in state.l3_interfaces():
            if ip_in_network(host.ip, iface.ip, iface.mask) is True:
                return dev, iface
    return None


def _owns(state: LabState, ip: str) -> bool:
    if state.owner_of_ip(ip) is not None:
        return True
    return any(host.ip == ip for host in state.hosts)


@rule(
    id="R010",
    name="DHCP configuration fault",
    category=ConceptTag.DHCP,
    severity=Severity.HIGH,
    osi_layer=OSILayer.L3,
    description=(
        "A DHCP pool does not match the subnet it serves, hands out an unusable default "
        "gateway or DNS server, excludes addresses outside its own network, or a DHCP "
        "client's segment has no pool and no relay at all."
    ),
    suggested_check=_CHECK,
)
def check_dhcp_configuration(ctx: RuleContext) -> list[Finding]:
    meta = check_dhcp_configuration.rule_meta  # type: ignore[attr-defined]
    findings: list[Finding] = []
    state = ctx.state

    for device in state.devices:
        for pool in device.dhcp_pools:
            findings.extend(_check_pool(meta, state, device, pool))

    for host in state.hosts:
        if not host.dhcp_enabled:
            continue
        findings.extend(_check_client(meta, state, host))

    return findings


def _check_pool(meta, state: LabState, device: Device, pool: DhcpPool) -> list[Finding]:
    findings: list[Finding] = []
    net = network_of(pool.network, pool.mask)

    # (a) The pool's network is not a subnet this device is actually attached to.
    if net is not None:
        attached = [
            (iface.name, network_of(iface.ip, iface.mask))
            for iface in device.interfaces
            if iface.ip and is_valid_netmask(iface.mask)
        ]
        if attached and not any(known == net for _name, known in attached):
            findings.append(
                make_finding(
                    meta,
                    message=(
                        f"DHCP pool {pool.name} on {device.name} serves network {net}, which "
                        f"is not a subnet {device.name} is attached to. Clients on the "
                        "intended segment either get no lease or get an address for the "
                        "wrong subnet."
                    ),
                    evidence=[
                        RuleEvidence(
                            source=_pool_label(device, pool),
                            detail=f"network {pool.network} {pool.mask}",
                        ),
                        RuleEvidence(
                            source=f"{device.name} / interfaces",
                            detail=(
                                "attached subnets: "
                                + ", ".join(
                                    f"{name}={known}" for name, known in attached if known
                                )
                            ),
                        ),
                    ],
                    affected=[device.name, pool.name],
                )
            )

    # (b) The default gateway the pool hands out.
    if not pool.default_router:
        findings.append(
            make_finding(
                meta,
                message=(
                    f"DHCP pool {pool.name} on {device.name} hands out no default-router, so "
                    "its clients receive an address but no gateway."
                ),
                evidence=[
                    RuleEvidence(
                        source=_pool_label(device, pool),
                        detail=f"network {pool.network} {pool.mask}, no default-router",
                    )
                ],
                affected=[device.name, pool.name],
            )
        )
    else:
        if net is not None and ip_in_network(pool.default_router, pool.network, pool.mask) is False:
            findings.append(
                make_finding(
                    meta,
                    message=(
                        f"DHCP pool {pool.name} on {device.name} hands out default-router "
                        f"{pool.default_router}, which is outside the pool's own network "
                        f"{net}. Every client it serves gets a gateway it cannot ARP for."
                    ),
                    evidence=[
                        RuleEvidence(
                            source=_pool_label(device, pool),
                            detail=(
                                f"network {pool.network} {pool.mask}, "
                                f"default-router {pool.default_router}"
                            ),
                        )
                    ],
                    affected=[device.name, pool.name],
                )
            )
        elif not _owns(state, pool.default_router):
            findings.append(
                make_finding(
                    meta,
                    message=(
                        f"DHCP pool {pool.name} on {device.name} hands out default-router "
                        f"{pool.default_router}, but no interface in the topology owns that "
                        "address, so nothing will answer for it."
                    ),
                    evidence=[
                        RuleEvidence(
                            source=_pool_label(device, pool),
                            detail=f"default-router {pool.default_router}",
                        ),
                        RuleEvidence(
                            source="topology",
                            detail=(
                                "L3 interface addresses present: "
                                + ", ".join(
                                    f"{d.name} {i.name}={i.ip}" for d, i in state.l3_interfaces()
                                )
                            ),
                        ),
                    ],
                    affected=[device.name, pool.name],
                )
            )

    # (c) An excluded address that is not in this pool's network.
    for excluded in pool.excluded:
        if net is None or ip_in_network(excluded, pool.network, pool.mask) is not False:
            continue
        findings.append(
            make_finding(
                meta,
                severity=Severity.MEDIUM,
                message=(
                    f"DHCP pool {pool.name} on {device.name} excludes {excluded}, which is "
                    f"not part of its network {net}. The address that actually needs "
                    "excluding is still inside the pool and will be handed to a client."
                ),
                evidence=[
                    RuleEvidence(
                        source=_pool_label(device, pool),
                        detail=(
                            f"network {pool.network} {pool.mask}, excluded "
                            + ", ".join(pool.excluded)
                        ),
                    )
                ],
                affected=[device.name, pool.name],
            )
        )

    # (e) A DNS server address handed out that belongs to nothing in the topology.
    for dns in pool.dns_servers:
        if _owns(state, dns):
            continue
        findings.append(
            make_finding(
                meta,
                message=(
                    f"DHCP pool {pool.name} on {device.name} hands out DNS server {dns}, but "
                    "no device or host in the topology has that address, so every client it "
                    "serves fails name resolution."
                ),
                evidence=[
                    RuleEvidence(
                        source=_pool_label(device, pool),
                        detail=f"dns-server {', '.join(pool.dns_servers)}",
                    ),
                    RuleEvidence(
                        source="topology",
                        detail=(
                            "host addresses present: "
                            + ", ".join(f"{h.name}={h.ip}" for h in state.hosts if h.ip)
                        ),
                    ),
                ],
                affected=[device.name, pool.name],
            )
        )

    return findings


def _check_client(meta, state: LabState, host) -> list[Finding]:
    """A DHCP client whose segment nothing is prepared to serve."""
    segment = _segment_interface(state, host)
    if segment is None:
        return []
    device, iface = segment
    net = network_of(iface.ip, iface.mask)
    if net is None:
        return []

    for candidate in state.devices:
        for pool in candidate.dhcp_pools:
            if network_of(pool.network, pool.mask) == net:
                return []

    if iface.helper_addresses:
        unreachable = [h for h in iface.helper_addresses if not _owns(state, h)]
        detail = (
            f"ip helper-address {', '.join(iface.helper_addresses)}"
            if not unreachable
            else f"ip helper-address {', '.join(unreachable)} — no device owns that address"
        )
        message = (
            f"{host.name} is a DHCP client on {net}, and the relay on {device.name} "
            f"{iface.name} forwards to {', '.join(iface.helper_addresses)}, but no pool "
            f"anywhere in the topology serves {net}."
        )
    else:
        detail = "no ip helper-address configured"
        message = (
            f"{host.name} is a DHCP client on {net}, but no device has a DHCP pool for that "
            f"network and {device.name} {iface.name} has no ip helper-address, so no DHCP "
            "server can ever answer it."
        )

    return [
        make_finding(
            meta,
            severity=Severity.CRITICAL,
            message=message,
            evidence=[
                RuleEvidence(source=host.name, detail="configured for DHCP, no static address"),
                RuleEvidence(source=f"{device.name} / {iface.name}", detail=detail),
            ],
            affected=[host.name, device.name, iface.name],
        )
    ]
