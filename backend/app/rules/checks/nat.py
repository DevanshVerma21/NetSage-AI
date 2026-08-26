"""R013 NAT configuration fault.

NAT is only checkable structurally: the translation itself cannot be observed in a static
snapshot, but the preconditions for it can, and every one of them is a hard invariant rather
than a matter of style. A device that carries ``nat_rules`` at all has declared the intent to
translate, which is what makes these deterministic:

* no interface is marked ``ip nat inside``, or none is marked ``ip nat outside``;
* a rule names an access list the device does not have;
* a dynamic rule has neither a pool nor overload, so it has no global address to use;
* the source network a dynamic rule matches exists on no inside interface;
* a static rule's ``inside_local`` address belongs to no host or interface, or its
  ``inside_global`` address is not on the outside interface's subnet.
"""

from __future__ import annotations

from backend.app.models.enums import ConceptTag, NatSide, OSILayer, Severity
from backend.app.models.lab_state import Device, LabState, NatRule
from backend.app.netutils import ip_in_network, is_valid_netmask, network_of
from backend.app.rules.engine import Finding, RuleContext, RuleEvidence, make_finding, rule

_CHECK = "show ip nat translations  /  show ip nat statistics  /  show running-config | include nat"


def _rule_text(rule_entry: NatRule) -> str:
    parts = [f"ip nat {rule_entry.kind}"]
    if rule_entry.inside_local:
        parts.append(f"inside source static {rule_entry.inside_local}")
    if rule_entry.inside_global:
        parts.append(str(rule_entry.inside_global))
    if rule_entry.acl_name:
        parts.append(f"list {rule_entry.acl_name}")
    if rule_entry.pool_name:
        parts.append(f"pool {rule_entry.pool_name}")
    if rule_entry.out_interface:
        parts.append(f"interface {rule_entry.out_interface}")
    return " ".join(parts)


def _sides(device: Device) -> tuple[list[str], list[str]]:
    inside = [i.name for i in device.interfaces if i.nat_side == NatSide.INSIDE]
    outside = [i.name for i in device.interfaces if i.nat_side == NatSide.OUTSIDE]
    return inside, outside


def _side_summary(device: Device) -> str:
    inside, outside = _sides(device)
    return (
        "ip nat inside: " + (", ".join(inside) or "none") + " | "
        "ip nat outside: " + (", ".join(outside) or "none")
    )


def _owns(state: LabState, ip: str) -> bool:
    if state.owner_of_ip(ip) is not None:
        return True
    return any(host.ip == ip for host in state.hosts)


@rule(
    id="R013",
    name="NAT configuration fault",
    category=ConceptTag.NAT,
    severity=Severity.HIGH,
    osi_layer=OSILayer.L3,
    description=(
        "A device configured for NAT cannot translate: an inside or outside interface is "
        "not designated, the translation rule references something that does not exist, or "
        "a dynamic rule has no global address to translate into."
    ),
    suggested_check=_CHECK,
)
def check_nat_configuration(ctx: RuleContext) -> list[Finding]:
    meta = check_nat_configuration.rule_meta  # type: ignore[attr-defined]
    findings: list[Finding] = []
    state = ctx.state

    for device in state.devices:
        if not device.nat_rules:
            continue
        findings.extend(_check_device(meta, state, device))

    return findings


def _check_device(meta, state: LabState, device: Device) -> list[Finding]:
    findings: list[Finding] = []
    inside, outside = _sides(device)
    rules_text = "; ".join(_rule_text(entry) for entry in device.nat_rules)

    def evidence(extra: RuleEvidence | None = None) -> list[RuleEvidence]:
        items = [
            RuleEvidence(source=f"{device.name} / nat", detail=rules_text),
            RuleEvidence(source=f"{device.name} / interfaces", detail=_side_summary(device)),
        ]
        if extra is not None:
            items.insert(1, extra)
        return items

    # (a) A missing inside or outside designation stops translation entirely.
    if not inside or not outside:
        missing = " and ".join(
            label for label, present in (("inside", inside), ("outside", outside)) if not present
        )
        findings.append(
            make_finding(
                meta,
                severity=Severity.CRITICAL,
                message=(
                    f"{device.name} is configured to translate addresses but no interface is "
                    f"marked ip nat {missing}. NAT never runs, so inside hosts leave with "
                    "their private addresses and the replies never come back."
                ),
                evidence=evidence(),
                affected=[device.name],
            )
        )

    for entry in device.nat_rules:
        # (b) A rule pointing at an access list the device does not have.
        if entry.acl_name and device.acl(entry.acl_name) is None:
            findings.append(
                make_finding(
                    meta,
                    message=(
                        f"{device.name} translates traffic matched by access list "
                        f"{entry.acl_name}, but no such access list exists on the device, so "
                        "the rule matches nothing and no host is translated."
                    ),
                    evidence=evidence(
                        RuleEvidence(
                            source=f"{device.name} / access lists",
                            detail=(
                                "access lists present: "
                                + (", ".join(acl.name for acl in device.acls) or "none")
                            ),
                        )
                    ),
                    affected=[device.name, entry.acl_name],
                )
            )
            continue

        # (c) A dynamic rule with no pool and no overload has no global address.
        if entry.kind == "dynamic" and not entry.pool_name and not entry.out_interface:
            findings.append(
                make_finding(
                    meta,
                    message=(
                        f"{device.name} has a dynamic NAT rule with neither an address pool "
                        "nor an outside interface to overload, so it has no global address to "
                        "translate into and every inside host is left untranslated."
                    ),
                    evidence=evidence(),
                    affected=[device.name],
                )
            )
            continue

        # (d) The source network the rule matches is not on any inside interface.
        if entry.acl_name:
            findings.extend(_check_nat_acl(meta, device, entry, inside, evidence))
            continue

        # (e) A static rule whose local address belongs to nothing.
        if entry.inside_local and not _owns(state, entry.inside_local):
            findings.append(
                make_finding(
                    meta,
                    message=(
                        f"{device.name} statically translates {entry.inside_local}, but no host "
                        "or interface in the topology has that address, so the translation "
                        "never applies to the server it was meant for."
                    ),
                    evidence=evidence(
                        RuleEvidence(
                            source="topology",
                            detail=(
                                "host addresses present: "
                                + ", ".join(f"{h.name}={h.ip}" for h in state.hosts if h.ip)
                            ),
                        )
                    ),
                    affected=[device.name, entry.inside_local],
                )
            )

    return findings


def _check_nat_acl(meta, device: Device, entry: NatRule, inside: list[str], evidence) -> list[Finding]:
    """A NAT access list that matches a source network none of the inside interfaces serve."""
    acl = device.acl(entry.acl_name or "")
    if acl is None or not inside:
        return []

    inside_nets = []
    for name in inside:
        iface = device.interface(name)
        if iface and iface.ip and is_valid_netmask(iface.mask):
            net = network_of(iface.ip, iface.mask)
            if net is not None:
                inside_nets.append((name, net))
    if not inside_nets:
        return []

    findings: list[Finding] = []
    for acl_entry in acl.entries:
        source = acl_entry.src
        if not source or source.lower() == "any":
            return []  # Matches everything, including the inside networks.
        if any(ip_in_network(source, str(net.network_address), str(net.netmask)) is True
               for _name, net in inside_nets):
            return []
        findings.append(
            make_finding(
                meta,
                message=(
                    f"{device.name} translates source network {source} for NAT, but that "
                    "network is on none of its inside interfaces, so the traffic that "
                    "actually arrives is never matched and never translated."
                ),
                evidence=evidence(
                    RuleEvidence(
                        source=f"{device.name} / {entry.acl_name}",
                        detail=(
                            f"permit {source} "
                            + (acl_entry.src_wildcard or "")
                        ).strip(),
                    )
                ),
                affected=[device.name, str(entry.acl_name)],
            )
        )
    return findings[:1]
