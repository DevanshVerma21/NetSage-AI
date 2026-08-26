"""R014 wireless guest isolation and SSID faults.

The isolation sub-case is the security-relevant one and is driven by declared intent: a case
states that a guest client must *not* reach an internal host, and the rule reports when
nothing in the wireless configuration enforces that. The remaining sub-cases are structural
invariants of the SSID configuration itself — an SSID a client joins that no access point
defines, a guest SSID sharing a VLAN with internal hosts, and an access point whose uplink
is down so no client can associate at all.
"""

from __future__ import annotations

from typing import Optional

from backend.app.models.enums import (
    ConceptTag,
    DeviceKind,
    FlowExpect,
    OSILayer,
    Severity,
)
from backend.app.models.lab_state import Device, LabState, Ssid
from backend.app.rules.engine import Finding, RuleContext, RuleEvidence, make_finding, rule

_CHECK = "show wlan summary  /  show ssid  /  show running-config | section ssid"
_AP_KINDS = (DeviceKind.ACCESS_POINT, DeviceKind.WLC)


def _find_ssid(state: LabState, name: str) -> Optional[tuple[Device, Ssid]]:
    for device in state.devices:
        for ssid in device.ssids:
            if ssid.name == name:
                return device, ssid
    return None


def _ssid_text(ssid: Ssid) -> str:
    return (
        f"ssid {ssid.name}: vlan {ssid.vlan}, guest={ssid.is_guest}, "
        f"security {ssid.security or 'unset'}, "
        f"isolation {ssid.isolation_acl or 'none'}"
    )


@rule(
    id="R014",
    name="Wireless guest isolation or SSID fault",
    category=ConceptTag.WIRELESS,
    severity=Severity.HIGH,
    osi_layer=OSILayer.L2,
    description=(
        "Guest wireless traffic is not isolated from the internal network as declared, a "
        "client is joined to an SSID no access point defines, a guest SSID shares a VLAN "
        "with internal hosts, or an access point's uplink is down."
    ),
    suggested_check=_CHECK,
)
def check_wireless_configuration(ctx: RuleContext) -> list[Finding]:
    meta = check_wireless_configuration.rule_meta  # type: ignore[attr-defined]
    findings: list[Finding] = []
    state = ctx.state
    reported: set[tuple[str, str]] = set()

    def add(key: tuple[str, str], finding: Finding) -> None:
        if key in reported:
            return
        reported.add(key)
        findings.append(finding)

    # (a) A guest client that is supposed to be kept off the internal network, and is not.
    for flow in ctx.intended_flows:
        if flow.expect != FlowExpect.DENY:
            continue
        client = state.host(flow.src)
        target = state.host(flow.dst)
        if client is None or target is None or not client.ssid:
            continue
        found = _find_ssid(state, client.ssid)
        if found is None:
            continue  # sub-case (b) reports an SSID nothing defines.
        device, ssid = found
        if not ssid.is_guest:
            continue
        enforced = bool(ssid.isolation_acl) and device.acl(ssid.isolation_acl or "") is not None
        if enforced:
            continue
        reason = (
            f"isolation list {ssid.isolation_acl} is named but does not exist on {device.name}"
            if ssid.isolation_acl
            else "no client isolation and no isolation ACL are configured"
        )
        add(
            ("isolation", f"{client.name}/{target.name}"),
            make_finding(
                meta,
                severity=Severity.CRITICAL,
                message=(
                    f"Guest SSID {ssid.name} on {device.name} does not isolate its clients: "
                    f"{reason}. {client.name} can reach {target.name}, which the network is "
                    "supposed to deny — guest traffic is on the internal network."
                ),
                evidence=[
                    RuleEvidence(source=f"{device.name} / {ssid.name}", detail=_ssid_text(ssid)),
                    RuleEvidence(
                        source="intended flow",
                        detail=(
                            f"{flow.src} -> {flow.dst} is expected to be denied"
                            + (f" — {flow.note}" if flow.note else "")
                        ),
                    ),
                    RuleEvidence(
                        source=client.name,
                        detail=f"wireless client on SSID {client.ssid}, VLAN {client.vlan}",
                    ),
                ],
                affected=[device.name, ssid.name, client.name, target.name],
            ),
        )

    # (b) A client joined to an SSID nothing broadcasts, or joined on the wrong VLAN.
    for host in state.hosts:
        if not host.ssid:
            continue
        found = _find_ssid(state, host.ssid)
        if found is None:
            defined = [
                f"{d.name}:{s.name}" for d in state.devices for s in d.ssids
            ]
            add(
                ("unknown-ssid", host.name),
                make_finding(
                    meta,
                    severity=Severity.CRITICAL,
                    message=(
                        f"{host.name} is configured for SSID {host.ssid}, but no access point "
                        "or controller in the topology broadcasts that SSID, so the client "
                        "never associates."
                    ),
                    evidence=[
                        RuleEvidence(
                            source=host.name, detail=f"wireless client, ssid {host.ssid}"
                        ),
                        RuleEvidence(
                            source="topology / wireless",
                            detail="SSIDs defined: " + (", ".join(defined) or "none"),
                        ),
                    ],
                    affected=[host.name, host.ssid],
                ),
            )
            continue
        device, ssid = found
        if ssid.vlan is not None and host.vlan is not None and ssid.vlan != host.vlan:
            add(
                ("vlan-map", host.name),
                make_finding(
                    meta,
                    message=(
                        f"{host.name} is on SSID {ssid.name}, which {device.name} maps to VLAN "
                        f"{ssid.vlan}, but the client is a member of VLAN {host.vlan}. Its "
                        "traffic lands in the wrong subnet and it never reaches its gateway."
                    ),
                    evidence=[
                        RuleEvidence(source=f"{device.name} / {ssid.name}", detail=_ssid_text(ssid)),
                        RuleEvidence(
                            source=host.name,
                            detail=f"ssid {host.ssid}, VLAN {host.vlan}, ip {host.ip or 'none'}",
                        ),
                    ],
                    affected=[host.name, ssid.name, f"VLAN{ssid.vlan}"],
                ),
            )

    # (c) A guest SSID sharing a VLAN with internal hosts.
    for device in state.devices:
        for ssid in device.ssids:
            if not ssid.is_guest or ssid.vlan is None:
                continue
            internal = [
                host.name
                for host in state.hosts
                if host.vlan == ssid.vlan and not host.ssid
            ]
            if not internal:
                continue
            add(
                ("shared-vlan", f"{device.name}/{ssid.name}"),
                make_finding(
                    meta,
                    severity=Severity.CRITICAL,
                    message=(
                        f"Guest SSID {ssid.name} on {device.name} is mapped to VLAN "
                        f"{ssid.vlan}, the same VLAN as internal hosts "
                        f"{', '.join(internal)}. Guests share the internal broadcast domain, "
                        "so isolation cannot be enforced at Layer 3 at all."
                    ),
                    evidence=[
                        RuleEvidence(source=f"{device.name} / {ssid.name}", detail=_ssid_text(ssid)),
                        RuleEvidence(
                            source="topology / hosts",
                            detail=(
                                "wired hosts in that VLAN: "
                                + ", ".join(
                                    f"{h.name}={h.ip}"
                                    for h in state.hosts
                                    if h.vlan == ssid.vlan and not h.ssid
                                )
                            ),
                        ),
                    ],
                    affected=[device.name, ssid.name, f"VLAN{ssid.vlan}", *internal],
                ),
            )

    # (d) An access point whose only uplink is down: no client can associate through it.
    for device in state.devices:
        if device.kind not in _AP_KINDS or not device.ssids:
            continue
        uplinks = [
            iface
            for link in state.links_for(device.name)
            for iface in [
                device.interface(
                    link.a_interface if link.a_device.lower() == device.name.lower()
                    else link.b_interface
                )
            ]
            if iface is not None
        ]
        if not uplinks or not all(iface.is_down for iface in uplinks):
            continue
        clients = [
            host.name
            for host in state.hosts
            if host.ssid and any(host.ssid == s.name for s in device.ssids)
        ]
        if not clients:
            continue
        add(
            ("ap-uplink", device.name),
            make_finding(
                meta,
                severity=Severity.CRITICAL,
                message=(
                    f"Every uplink on {device.name} is down "
                    f"({', '.join(i.name for i in uplinks)}), so {', '.join(clients)} can "
                    "associate to the SSID but reach nothing beyond the access point."
                ),
                evidence=[
                    RuleEvidence(
                        source=f"{device.name} / uplinks",
                        detail="; ".join(
                            f"{i.name} admin_state={i.admin_state.value} "
                            f"line_protocol={i.oper_state.value}"
                            for i in uplinks
                        ),
                    ),
                    RuleEvidence(
                        source=f"{device.name} / wireless",
                        detail="; ".join(_ssid_text(s) for s in device.ssids),
                    ),
                ],
                affected=[device.name, *clients],
            ),
        )

    return findings
