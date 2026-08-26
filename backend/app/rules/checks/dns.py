"""R011 DNS configuration or reachability fault.

Driven entirely by declared intent: only a flow the case marks as DNS (``proto == "dns"``
or ``port == 53``) makes a client's resolver configuration checkable. Without that intent
there is no deterministic way to know which host is supposed to be the resolver, and
guessing from an address that merely looks like a server would report faults in working
labs — so a case with no DNS flow produces no R011 finding at all.

Four faults are reported: the client has no resolver, the client points at something other
than the intended resolver, a configured resolver address belongs to nothing in the
topology, and the intended resolver is cabled to a port that is down.
"""

from __future__ import annotations

from typing import Optional

from backend.app.models.enums import ConceptTag, FlowExpect, OSILayer, Severity
from backend.app.models.lab_state import Device, Interface, LabState
from backend.app.rules.engine import Finding, RuleContext, RuleEvidence, make_finding, rule

_CHECK = "ipconfig /all  /  nslookup <name>  /  show running-config | include dns"


def _is_dns(flow) -> bool:
    return flow.proto.lower() == "dns" or flow.port == 53


def _owns(state: LabState, ip: str) -> bool:
    if state.owner_of_ip(ip) is not None:
        return True
    return any(host.ip == ip for host in state.hosts)


def _access_port(state: LabState, host) -> Optional[tuple[Device, Interface]]:
    """The switch port the host is cabled to, when the topology records one."""
    if not (host.connected_device and host.connected_interface):
        return None
    device = state.device(host.connected_device)
    if device is None:
        return None
    iface = device.interface(host.connected_interface)
    return (device, iface) if iface is not None else None


@rule(
    id="R011",
    name="DNS configuration or reachability fault",
    category=ConceptTag.DNS,
    severity=Severity.HIGH,
    osi_layer=OSILayer.L7,
    description=(
        "A host that is supposed to resolve names has no DNS server configured, is pointed "
        "at the wrong one, is pointed at an address nothing in the topology owns, or the "
        "intended resolver itself is unreachable."
    ),
    suggested_check=_CHECK,
)
def check_dns_configuration(ctx: RuleContext) -> list[Finding]:
    meta = check_dns_configuration.rule_meta  # type: ignore[attr-defined]
    findings: list[Finding] = []
    state = ctx.state
    reported: set[tuple[str, str]] = set()

    def add(key: tuple[str, str], finding: Finding) -> None:
        if key in reported:
            return
        reported.add(key)
        findings.append(finding)

    for flow in ctx.intended_flows:
        if flow.expect != FlowExpect.PERMIT or not _is_dns(flow):
            continue
        client = state.host(flow.src)
        server = state.host(flow.dst)
        if client is None:
            continue

        # (a) No resolver at all.
        if not client.dns_servers:
            add(
                ("none", client.name),
                make_finding(
                    meta,
                    severity=Severity.CRITICAL,
                    message=(
                        f"{client.name} is expected to resolve names using {flow.dst} but has "
                        "no DNS server configured, so every name lookup it makes fails."
                    ),
                    evidence=[
                        RuleEvidence(source=client.name, detail="no dns-server configured"),
                        RuleEvidence(
                            source="intended flow",
                            detail=f"{flow.src} -> {flow.dst} DNS is expected to be permitted",
                        ),
                    ],
                    affected=[client.name],
                ),
            )
            continue

        # (b) Pointed somewhere other than the intended resolver.
        if server is not None and server.ip and server.ip not in client.dns_servers:
            add(
                ("wrong", client.name),
                make_finding(
                    meta,
                    message=(
                        f"{client.name} is configured with DNS server "
                        f"{', '.join(client.dns_servers)}, but the resolver it is supposed to "
                        f"use is {server.name} at {server.ip}. Name resolution never reaches "
                        "the server that holds the records."
                    ),
                    evidence=[
                        RuleEvidence(
                            source=client.name,
                            detail=f"dns-server {', '.join(client.dns_servers)}",
                        ),
                        RuleEvidence(
                            source=server.name,
                            detail=f"the intended resolver, address {server.ip}",
                        ),
                        RuleEvidence(
                            source="intended flow",
                            detail=f"{flow.src} -> {flow.dst} DNS is expected to be permitted",
                        ),
                    ],
                    affected=[client.name, server.name],
                ),
            )

        # (c) A configured resolver address that belongs to nothing.
        for address in client.dns_servers:
            if _owns(state, address):
                continue
            add(
                ("unowned", f"{client.name}/{address}"),
                make_finding(
                    meta,
                    message=(
                        f"{client.name} is configured with DNS server {address}, but no device "
                        "or host in the topology has that address, so the query is sent to "
                        "something that does not exist."
                    ),
                    evidence=[
                        RuleEvidence(
                            source=client.name,
                            detail=f"dns-server {', '.join(client.dns_servers)}",
                        ),
                        RuleEvidence(
                            source="topology",
                            detail=(
                                "host addresses present: "
                                + ", ".join(f"{h.name}={h.ip}" for h in state.hosts if h.ip)
                            ),
                        ),
                    ],
                    affected=[client.name, address],
                ),
            )

        # (d) The intended resolver is cabled to a port that is down.
        if server is None:
            continue
        port = _access_port(state, server)
        if port is None:
            continue
        device, iface = port
        if not iface.is_down:
            continue
        add(
            ("port", server.name),
            make_finding(
                meta,
                severity=Severity.CRITICAL,
                message=(
                    f"{server.name} is the DNS server for {client.name}, but the port it is "
                    f"cabled to ({device.name} {iface.name}) is down, so the DNS service is "
                    "unreachable however the clients are configured."
                ),
                evidence=[
                    RuleEvidence(
                        source=f"{device.name} / {iface.name}",
                        detail=(
                            f"admin_state={iface.admin_state.value} "
                            f"line_protocol={iface.oper_state.value}, "
                            f"{server.name} is attached here"
                        ),
                    ),
                    RuleEvidence(
                        source=client.name,
                        detail=f"dns-server {', '.join(client.dns_servers)}",
                    ),
                ],
                affected=[server.name, device.name, iface.name],
            ),
        )

    return findings
