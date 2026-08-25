"""R006 missing route — a mandatory check from the company document.

Scope, stated plainly: this evaluates the **first Layer 3 hop** — the device that owns the
source host's default gateway. That single hop is where the overwhelming majority of lab
routing faults live (no inter-VLAN route, no default route, ``ip routing`` never enabled),
and checking it is fully deterministic. Full multi-hop path simulation is deliberately out
of scope for the prototype; the rule says so in its finding text rather than implying a
completeness it does not have.

The check is driven by each case's declared ``intended_flows``. Without a declared intent
there is no way to decide whether a missing route is a fault or the desired policy.
"""

from __future__ import annotations

from backend.app.models.enums import ConceptTag, FlowExpect, OSILayer, Severity
from backend.app.models.lab_state import Device
from backend.app.netutils import is_valid_netmask, ip_in_network, network_of, same_subnet
from backend.app.rules.engine import Finding, RuleContext, RuleEvidence, make_finding, rule


@rule(
    id="R006",
    name="Missing route",
    category=ConceptTag.ROUTING,
    severity=Severity.HIGH,
    osi_layer=OSILayer.L3,
    description=(
        "The first-hop router has no connected, static, dynamic or default route covering "
        "the destination of a flow the network is supposed to permit — or IP routing is "
        "disabled on it entirely."
    ),
    mandatory=True,
    suggested_check="show ip route",
)
def check_missing_route(ctx: RuleContext) -> list[Finding]:
    meta = check_missing_route.rule_meta  # type: ignore[attr-defined]
    findings: list[Finding] = []
    reported_routing_disabled: set[str] = set()

    for flow in ctx.intended_flows:
        if flow.expect != FlowExpect.PERMIT:
            continue

        src = ctx.state.host(flow.src)
        dst = ctx.state.host(flow.dst)
        if src is None or dst is None or not (src.ip and dst.ip):
            continue  # Cannot evaluate; not evidence of a fault.

        # Same subnet means no routing decision is involved at all.
        if is_valid_netmask(src.mask) and same_subnet(src.ip, dst.ip, src.mask) is True:
            continue

        if not src.gateway:
            continue  # R003 reports the missing gateway.
        owner = ctx.state.owner_of_ip(src.gateway)
        if owner is None:
            continue  # R003 reports the unowned gateway.
        router, _gw_iface = owner

        # Sub-case: routing switched off on the first hop.
        if not router.ip_routing_enabled:
            if router.name not in reported_routing_disabled:
                reported_routing_disabled.add(router.name)
                findings.append(
                    make_finding(
                        meta,
                        severity=Severity.CRITICAL,
                        message=(
                            f"{router.name} is the first-hop gateway for {src.name} but IP "
                            "routing is disabled on it, so no traffic is routed between "
                            "subnets regardless of the routing table."
                        ),
                        evidence=[
                            RuleEvidence(
                                source=f"{router.name} / global config",
                                detail="ip routing is not enabled (no ip routing)",
                            )
                        ],
                        affected=[router.name],
                        suggested_mutation={
                            "type": "enable_ip_routing",
                            "device": router.name,
                        },
                    )
                )
            continue

        matched, reason = _route_to(router, dst.ip)
        if matched:
            continue

        dst_net = network_of(dst.ip, dst.mask) if is_valid_netmask(dst.mask) else None
        dst_label = str(dst_net) if dst_net else dst.ip
        findings.append(
            make_finding(
                meta,
                message=(
                    f"{router.name} (first-hop gateway for {src.name}) has no route to "
                    f"{dst_label}, so the intended flow {flow.src} -> {flow.dst} cannot be "
                    "delivered. Checked at the first Layer 3 hop only."
                ),
                evidence=[
                    RuleEvidence(
                        source=f"{router.name} / routing table",
                        detail=_route_table_summary(router),
                    ),
                    RuleEvidence(
                        source="intended flow",
                        detail=(
                            f"{flow.src} -> {flow.dst} ({flow.proto}"
                            + (f"/{flow.port}" if flow.port else "")
                            + ") is expected to be permitted"
                        ),
                    ),
                    RuleEvidence(source="lookup result", detail=reason),
                ],
                affected=[router.name, src.name, dst.name],
                suggested_mutation=(
                    {
                        "type": "add_static_route",
                        "device": router.name,
                        "prefix": str(dst_net.network_address),
                        "mask": dst.mask,
                    }
                    if dst_net
                    else None
                ),
            )
        )

    return _dedupe(findings)


def _route_to(router: Device, dst_ip: str) -> tuple[bool, str]:
    """Whether ``router`` has any route covering ``dst_ip``, plus a human-readable reason."""
    # Connected routes: an up interface whose own subnet contains the destination.
    for iface in router.interfaces:
        if not (iface.ip and is_valid_netmask(iface.mask)) or iface.is_down:
            continue
        if ip_in_network(dst_ip, iface.ip, iface.mask) is True:
            return True, f"connected via {iface.name} ({iface.ip}/{iface.mask})"

    # Explicit routing-table entries.
    for route in router.routes:
        if route.is_default:
            return True, f"default route via {route.next_hop or route.out_interface}"
        if not is_valid_netmask(route.mask):
            continue
        if ip_in_network(dst_ip, route.prefix, route.mask) is True:
            return True, (
                f"{route.protocol.value} route {route.prefix}/{route.mask} via "
                f"{route.next_hop or route.out_interface}"
            )

    return False, f"no connected, static, dynamic or default route matches {dst_ip}"


def _route_table_summary(router: Device) -> str:
    parts: list[str] = []
    for iface in router.interfaces:
        if iface.ip and is_valid_netmask(iface.mask) and not iface.is_down:
            net = network_of(iface.ip, iface.mask)
            parts.append(f"C {net} via {iface.name}")
    for route in router.routes:
        target = route.next_hop or route.out_interface or "?"
        if route.is_default:
            parts.append(f"S* 0.0.0.0/0 via {target}")
        else:
            parts.append(f"{route.protocol.value[0].upper()} {route.prefix}/{route.mask} via {target}")
    return "; ".join(parts) if parts else "routing table is empty"


def _dedupe(findings: list[Finding]) -> list[Finding]:
    """Collapse identical findings produced by several flows sharing one missing route."""
    seen: set[tuple[str, str]] = set()
    unique: list[Finding] = []
    for finding in findings:
        key = (finding.rule_id, finding.message)
        if key in seen:
            continue
        seen.add(key)
        unique.append(finding)
    return unique
