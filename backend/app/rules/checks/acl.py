"""R012 an ACL blocks (or fails to block) an intended flow.

The rule evaluates the access lists that are actually bound to the first Layer 3 hop the
way the IOS does: entries in sequence order, first match wins, an implicit deny at the end.
It is driven by ``intended_flows``, so an ACL is never reported for looking restrictive —
only for producing a verdict that contradicts declared intent. That single comparison is
what surfaces every sub-type at once: an explicit deny of wanted traffic, a list bound in
the wrong direction or on the wrong interface (the traffic then meets the wrong list, or
none at all), a mistyped source or destination, and traffic that was simply never permitted
and dies on the implicit deny.
"""

from __future__ import annotations

from typing import Optional

from backend.app.models.enums import AclAction, ConceptTag, FlowExpect, OSILayer, Severity
from backend.app.models.lab_state import Acl, AclEntry, Device, LabState
from backend.app.netutils import ip_in_network, is_valid_netmask, parse_ip
from backend.app.rules.engine import Finding, RuleContext, RuleEvidence, make_finding, rule

_CHECK = "show ip access-lists  /  show ip interface <if> | include access list"


def _matches_address(ip: str, spec: str, wildcard: Optional[str]) -> bool:
    if not spec or spec.lower() == "any":
        return True
    if wildcard is None or wildcard == "0.0.0.0":
        return ip == spec
    address, base, mask = parse_ip(ip), parse_ip(spec), parse_ip(wildcard)
    if address is None or base is None or mask is None:
        return False
    bits = int(mask)
    return (int(address) & ~bits) == (int(base) & ~bits)


def _matches_protocol(entry: AclEntry, proto: str) -> bool:
    return entry.protocol.lower() in ("ip", proto.lower())


def _matches_port(entry: AclEntry, port: Optional[int]) -> bool:
    if entry.port is None:
        return True
    if port is None:
        return False
    op = (entry.port_op or "eq").lower()
    if op == "eq":
        return port == entry.port
    if op == "neq":
        return port != entry.port
    if op == "gt":
        return port > entry.port
    if op == "lt":
        return port < entry.port
    return False


def _evaluate(acl: Acl, src_ip: str, dst_ip: str, proto: str, port: Optional[int]):
    """The list's verdict, plus the entry that produced it (``None`` = implicit deny)."""
    for entry in sorted(acl.entries, key=lambda e: e.seq):
        if (
            _matches_protocol(entry, proto)
            and _matches_address(src_ip, entry.src, entry.src_wildcard)
            and _matches_address(dst_ip, entry.dst, entry.dst_wildcard)
            and _matches_port(entry, port)
        ):
            return entry.action, entry
    return AclAction.DENY, None


def _entry_text(entry: Optional[AclEntry]) -> str:
    if entry is None:
        return "implicit deny at the end of the list"
    parts = [str(entry.seq), entry.action.value, entry.protocol, entry.src]
    if entry.src_wildcard:
        parts.append(entry.src_wildcard)
    parts.append(entry.dst)
    if entry.dst_wildcard:
        parts.append(entry.dst_wildcard)
    if entry.port is not None:
        parts.append(f"{entry.port_op or 'eq'} {entry.port}")
    return " ".join(parts)


def _acl_text(acl: Acl) -> str:
    body = "; ".join(_entry_text(entry) for entry in sorted(acl.entries, key=lambda e: e.seq))
    return f"ip access-list {acl.name}: {body or 'no entries'}"


def _iface_for(device: Device, ip: str) -> Optional[str]:
    for iface in device.interfaces:
        if not (iface.ip and is_valid_netmask(iface.mask)):
            continue
        if ip_in_network(ip, iface.ip, iface.mask) is True:
            return iface.name
    return None


def _bound_acls(state: LabState, device: Device, ingress: Optional[str], egress: Optional[str]):
    """The (acl, binding) pairs the flow actually traverses, in the order it meets them."""
    pairs = []
    for binding in device.acl_bindings:
        direction = binding.direction.lower()
        name = binding.interface.lower()
        if direction == "in" and ingress and name == ingress.lower():
            pairs.append(binding)
        elif direction == "out" and egress and name == egress.lower():
            pairs.append(binding)
    resolved = []
    for binding in pairs:
        acl = device.acl(binding.acl_name)
        if acl is not None:
            resolved.append((acl, binding))
    return resolved


@rule(
    id="R012",
    name="ACL blocks intended flow",
    category=ConceptTag.ACL,
    severity=Severity.HIGH,
    osi_layer=OSILayer.L4,
    description=(
        "An access list bound to the first-hop device denies traffic the network is supposed "
        "to permit, or permits traffic it is supposed to deny."
    ),
    suggested_check=_CHECK,
)
def check_acl_blocks_flow(ctx: RuleContext) -> list[Finding]:
    meta = check_acl_blocks_flow.rule_meta  # type: ignore[attr-defined]
    findings: list[Finding] = []
    state = ctx.state

    for flow in ctx.intended_flows:
        src, dst = state.host(flow.src), state.host(flow.dst)
        if src is None or dst is None or not (src.ip and dst.ip):
            continue
        if not src.gateway:
            continue  # R003 owns a missing gateway.
        owner = state.owner_of_ip(src.gateway)
        if owner is None:
            continue
        device, _gw_iface = owner

        ingress = _iface_for(device, src.ip)
        egress = _iface_for(device, dst.ip)
        traversed = _bound_acls(state, device, ingress, egress)

        verdict, entry, acl, binding = AclAction.PERMIT, None, None, None
        for candidate, candidate_binding in traversed:
            result, matched = _evaluate(candidate, src.ip, dst.ip, flow.proto, flow.port)
            if result == AclAction.DENY:
                verdict, entry, acl, binding = result, matched, candidate, candidate_binding
                break

        flow_label = (
            f"{flow.src} -> {flow.dst} ({flow.proto}"
            + (f"/{flow.port}" if flow.port else "")
            + ")"
        )

        if flow.expect == FlowExpect.PERMIT and verdict == AclAction.DENY and acl is not None:
            findings.append(
                make_finding(
                    meta,
                    severity=Severity.CRITICAL,
                    message=(
                        f"Access list {acl.name} on {device.name} {binding.interface} "
                        f"({binding.direction}) denies {flow_label}, which the network is "
                        f"supposed to permit: {_entry_text(entry)}."
                    ),
                    evidence=[
                        RuleEvidence(source=f"{device.name} / {acl.name}", detail=_acl_text(acl)),
                        RuleEvidence(
                            source=f"{device.name} / {binding.interface}",
                            detail=f"ip access-group {acl.name} {binding.direction}",
                        ),
                        RuleEvidence(
                            source="intended flow",
                            detail=f"{flow_label} is expected to be permitted",
                        ),
                    ],
                    affected=[device.name, acl.name, src.name, dst.name],
                )
            )
        elif flow.expect == FlowExpect.DENY and verdict == AclAction.PERMIT and device.acls:
            if traversed:
                detail = "; ".join(
                    f"{b.acl_name} {b.direction} on {b.interface}" for _a, b in traversed
                )
            else:
                detail = (
                    "no access list is bound to "
                    + (f"{ingress} in" if ingress else "the ingress interface")
                    + " or "
                    + (f"{egress} out" if egress else "the egress interface")
                )
            findings.append(
                make_finding(
                    meta,
                    message=(
                        f"{flow_label} is supposed to be denied, but nothing on {device.name} "
                        "stops it: the traffic reaches the destination. "
                        + (
                            "The lists that exist are bound where this traffic does not meet "
                            "them."
                            if device.acls and not traversed
                            else "It is permitted by the lists it does meet."
                        )
                    ),
                    evidence=[
                        RuleEvidence(source=f"{device.name} / acl bindings", detail=detail),
                        RuleEvidence(
                            source="intended flow",
                            detail=f"{flow_label} is expected to be denied"
                            + (f" — {flow.note}" if flow.note else ""),
                        ),
                        RuleEvidence(
                            source=f"{device.name} / access lists",
                            detail=(
                                "; ".join(_acl_text(a) for a in device.acls)
                                if device.acls
                                else "no access lists configured"
                            ),
                        ),
                    ],
                    affected=[device.name, src.name, dst.name],
                )
            )

    return findings
