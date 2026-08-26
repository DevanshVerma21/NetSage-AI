"""Reusable builders and ``show`` renderers for the case dataset.

Phase 5 needs 40 internally consistent cases. Hand-writing the ``show`` text for each one
invites exactly the inconsistency the validators exist to catch — an interface address that
appears in the LabState but in no output, a VLAN in the database that the ``show vlan brief``
capture forgets. So the outputs a device would print mechanically are *rendered from the
LabState*, which makes the six consistency invariants structural rather than a matter of
proofreading. Each case then adds only the outputs a human genuinely has to author: a ping,
a running-config excerpt, an nslookup.

This module is a data-generation helper only. It is not imported by the application; the
generated cases live explicitly in ``data/cases.json``.
"""

from __future__ import annotations

from typing import Iterable, Optional

from backend.app.models.enums import (
    AclAction,
    AdminState,
    DeviceKind,
    FlowExpect,
    LinkMode,
    NatSide,
    OperState,
    RouteProtocol,
    SwitchportMode,
)
from backend.app.models.lab_state import (
    Acl,
    AclBinding,
    AclEntry,
    Device,
    DhcpPool,
    Host,
    IntendedFlow,
    Interface,
    LabState,
    Link,
    NatRule,
    Route,
    Ssid,
    Vlan,
)
from backend.app.netutils import mask_to_prefix, network_of

# --------------------------------------------------------------------------------------
# builders — short names, because a case definition reads better as a table than as prose
# --------------------------------------------------------------------------------------


def ifc(
    name: str,
    ip: Optional[str] = None,
    mask: Optional[str] = None,
    *,
    vlan: Optional[int] = None,
    mode: Optional[str] = None,
    admin: str = "up",
    oper: str = "up",
    svi: bool = False,
    allowed: Iterable[int] = (),
    native: Optional[int] = None,
    nat: Optional[str] = None,
    helpers: Iterable[str] = (),
    description: Optional[str] = None,
) -> Interface:
    return Interface(
        name=name,
        ip=ip,
        mask=mask,
        admin_state=AdminState(admin),
        oper_state=OperState(oper),
        is_svi=svi or name.lower().startswith("vlan"),
        vlan=vlan,
        switchport_mode=SwitchportMode(mode) if mode else None,
        allowed_vlans=list(allowed),
        native_vlan=native,
        nat_side=NatSide(nat) if nat else None,
        helper_addresses=list(helpers),
        description=description,
    )


def vlan(vlan_id: int, name: str, status: str = "active") -> Vlan:
    return Vlan(vlan_id=vlan_id, name=name, status=status)


def route(
    prefix: str,
    mask: str,
    next_hop: Optional[str] = None,
    *,
    out_interface: Optional[str] = None,
    protocol: str = "static",
) -> Route:
    return Route(
        prefix=prefix,
        mask=mask,
        next_hop=next_hop,
        out_interface=out_interface,
        protocol=RouteProtocol(protocol),
    )


def ace(
    seq: int,
    action: str,
    protocol: str = "ip",
    src: str = "any",
    src_wildcard: Optional[str] = None,
    dst: str = "any",
    dst_wildcard: Optional[str] = None,
    *,
    port_op: Optional[str] = None,
    port: Optional[int] = None,
) -> AclEntry:
    return AclEntry(
        seq=seq,
        action=AclAction(action),
        protocol=protocol,
        src=src,
        src_wildcard=src_wildcard,
        dst=dst,
        dst_wildcard=dst_wildcard,
        port_op=port_op,
        port=port,
    )


def acl(name: str, *entries: AclEntry) -> Acl:
    return Acl(name=name, entries=list(entries))


def bind(acl_name: str, interface: str, direction: str) -> AclBinding:
    return AclBinding(acl_name=acl_name, interface=interface, direction=direction)


def pool(
    name: str,
    network: Optional[str] = None,
    mask: Optional[str] = None,
    *,
    router: Optional[str] = None,
    dns: Iterable[str] = (),
    excluded: Iterable[str] = (),
) -> DhcpPool:
    return DhcpPool(
        name=name,
        network=network,
        mask=mask,
        default_router=router,
        dns_servers=list(dns),
        excluded=list(excluded),
    )


def nat(
    kind: str,
    *,
    acl_name: Optional[str] = None,
    pool_name: Optional[str] = None,
    inside_local: Optional[str] = None,
    inside_global: Optional[str] = None,
    out_interface: Optional[str] = None,
) -> NatRule:
    return NatRule(
        kind=kind,
        acl_name=acl_name,
        pool_name=pool_name,
        inside_local=inside_local,
        inside_global=inside_global,
        out_interface=out_interface,
    )


def ssid(
    name: str,
    vlan_id: Optional[int] = None,
    *,
    guest: bool = False,
    isolation: Optional[str] = None,
    security: Optional[str] = None,
) -> Ssid:
    return Ssid(
        name=name, vlan=vlan_id, is_guest=guest, isolation_acl=isolation, security=security
    )


def dev(
    name: str,
    kind: str = "multilayer_switch",
    *,
    routing: bool = True,
    ifaces: Iterable[Interface] = (),
    vlans: Iterable[Vlan] = (),
    routes: Iterable[Route] = (),
    acls: Iterable[Acl] = (),
    bindings: Iterable[AclBinding] = (),
    pools: Iterable[DhcpPool] = (),
    nats: Iterable[NatRule] = (),
    ssids: Iterable[Ssid] = (),
) -> Device:
    return Device(
        name=name,
        kind=DeviceKind(kind),
        ip_routing_enabled=routing,
        interfaces=list(ifaces),
        vlans=list(vlans),
        routes=list(routes),
        acls=list(acls),
        acl_bindings=list(bindings),
        dhcp_pools=list(pools),
        nat_rules=list(nats),
        ssids=list(ssids),
    )


def host(
    name: str,
    ip: Optional[str] = None,
    mask: Optional[str] = "255.255.255.0",
    gw: Optional[str] = None,
    *,
    dns: Iterable[str] = (),
    vlan_id: Optional[int] = None,
    on: Optional[str] = None,
    port: Optional[str] = None,
    dhcp: bool = False,
    wifi: Optional[str] = None,
) -> Host:
    return Host(
        name=name,
        ip=ip,
        mask=mask if ip else None,
        gateway=gw,
        dns_servers=list(dns),
        vlan=vlan_id,
        connected_device=on,
        connected_interface=port,
        dhcp_enabled=dhcp,
        ssid=wifi,
    )


def link(
    a_device: str,
    a_interface: str,
    b_device: str,
    b_interface: str,
    *,
    mode: str = "access",
    vlan_id: Optional[int] = None,
    allowed: Iterable[int] = (),
    native: Optional[int] = None,
) -> Link:
    return Link(
        a_device=a_device,
        a_interface=a_interface,
        b_device=b_device,
        b_interface=b_interface,
        mode=LinkMode(mode),
        access_vlan=vlan_id,
        allowed_vlans=list(allowed),
        native_vlan=native,
    )


def flow(
    src: str,
    dst: str,
    proto: str = "ip",
    port: Optional[int] = None,
    *,
    expect: str = "permit",
    note: Optional[str] = None,
) -> IntendedFlow:
    return IntendedFlow(
        src=src, dst=dst, proto=proto, port=port, expect=FlowExpect(expect), note=note
    )


def state(
    devices: Iterable[Device], hosts: Iterable[Host], links: Iterable[Link] = ()
) -> LabState:
    return LabState(devices=list(devices), hosts=list(hosts), links=list(links))


# --------------------------------------------------------------------------------------
# renderers — everything a device prints mechanically, derived from the LabState itself
# --------------------------------------------------------------------------------------


def _short(name: str) -> str:
    for long, brief in (
        ("GigabitEthernet", "Gi"),
        ("FastEthernet", "Fa"),
        ("TenGigabitEthernet", "Te"),
        ("Serial", "Se"),
    ):
        if name.startswith(long):
            return brief + name[len(long) :]
    return name


def render_ip_int_brief(device: Device) -> str:
    lines = [
        "Interface                  IP-Address      OK? Method Status                Protocol"
    ]
    for iface in device.interfaces:
        status = (
            "administratively down"
            if iface.admin_state == AdminState.SHUTDOWN
            else ("up" if iface.oper_state == OperState.UP else "down")
        )
        protocol = "up" if iface.oper_state == OperState.UP else "down"
        method = "manual" if iface.ip else "unset"
        lines.append(
            f"{iface.name:<26} {iface.ip or 'unassigned':<15} YES {method:<6} "
            f"{status:<21} {protocol}"
        )
    return "\n".join(lines)


def _access_ports(device: Device, vlan_id: int) -> list[str]:
    return [
        _short(iface.name)
        for iface in device.interfaces
        if iface.switchport_mode == SwitchportMode.ACCESS and iface.vlan == vlan_id
    ]


def render_vlan_brief(device: Device) -> str:
    lines = [
        "VLAN Name                             Status    Ports",
        "---- -------------------------------- --------- -------------------------------",
    ]
    for entry in sorted(device.vlans, key=lambda v: v.vlan_id):
        ports = ", ".join(_access_ports(device, entry.vlan_id))
        lines.append(f"{entry.vlan_id:<4} {entry.name:<32} {entry.status:<9} {ports}")
    return "\n".join(lines)


def render_ip_route(device: Device) -> str:
    default = next((r for r in device.routes if r.is_default), None)
    lines = [
        "Codes: C - connected, S - static, S* - candidate default",
        "",
        (
            f"Gateway of last resort is {default.next_hop or default.out_interface} to network "
            "0.0.0.0"
            if default
            else "Gateway of last resort is not set"
        ),
        "",
    ]
    if not device.ip_routing_enabled:
        lines.append("     (ip routing is not enabled on this device)")
    for iface in device.interfaces:
        net = network_of(iface.ip, iface.mask)
        if net is None or iface.oper_state != OperState.UP:
            continue
        lines.append(f"C       {net} is directly connected, {iface.name}")
    for entry in device.routes:
        target = entry.next_hop or entry.out_interface or "?"
        code = "S*" if entry.is_default else entry.protocol.value[0].upper()
        prefix_len = mask_to_prefix(entry.mask)
        network = f"{entry.prefix}/{prefix_len}" if prefix_len is not None else entry.prefix
        via = f"via {entry.next_hop}" if entry.next_hop else f"is directly connected, {target}"
        lines.append(f"{code:<7} {network} [1/0] {via}")
    return "\n".join(lines)


def render_trunk(device: Device) -> str:
    trunks = [i for i in device.interfaces if i.switchport_mode == SwitchportMode.TRUNK]
    lines = ["Port        Mode         Encapsulation  Status        Native vlan"]
    for iface in trunks:
        status = "trunking" if iface.oper_state == OperState.UP else "not-trunking"
        lines.append(
            f"{_short(iface.name):<11} on           802.1q         {status:<13} "
            f"{iface.native_vlan if iface.native_vlan is not None else 1}"
        )
    lines.extend(["", "Port        Vlans allowed on trunk"])
    for iface in trunks:
        allowed = (
            ",".join(str(v) for v in sorted(iface.allowed_vlans))
            if iface.allowed_vlans
            else "1-4094"
        )
        lines.append(f"{_short(iface.name):<11} {allowed}")
    return "\n".join(lines)


def render_dhcp(device: Device) -> str:
    lines: list[str] = []
    for entry in device.dhcp_pools:
        for excluded in entry.excluded:
            lines.append(f"ip dhcp excluded-address {excluded}")
    for entry in device.dhcp_pools:
        lines.append(f"ip dhcp pool {entry.name}")
        if entry.network and entry.mask:
            lines.append(f" network {entry.network} {entry.mask}")
        if entry.default_router:
            lines.append(f" default-router {entry.default_router}")
        if entry.dns_servers:
            lines.append(" dns-server " + " ".join(entry.dns_servers))
        lines.append("!")
    for iface in device.interfaces:
        for helper in iface.helper_addresses:
            lines.append(f"interface {iface.name}")
            lines.append(f" ip helper-address {helper}")
            lines.append("!")
    return "\n".join(lines)


def _ace_text(entry: AclEntry) -> str:
    parts = [str(entry.seq), entry.action.value, entry.protocol]
    parts.append(entry.src if entry.src_wildcard or entry.src == "any" else f"host {entry.src}")
    if entry.src_wildcard:
        parts.append(entry.src_wildcard)
    parts.append(entry.dst if entry.dst_wildcard or entry.dst == "any" else f"host {entry.dst}")
    if entry.dst_wildcard:
        parts.append(entry.dst_wildcard)
    if entry.port is not None:
        parts.append(f"{entry.port_op or 'eq'} {entry.port}")
    return "    " + " ".join(parts)


def render_acls(device: Device) -> str:
    lines: list[str] = []
    for entry in device.acls:
        lines.append(f"Extended IP access list {entry.name}")
        lines.extend(_ace_text(ace_entry) for ace_entry in sorted(entry.entries, key=lambda e: e.seq))
    return "\n".join(lines)


def render_acl_bindings(device: Device) -> str:
    lines: list[str] = []
    for binding in device.acl_bindings:
        lines.append(f"interface {binding.interface}")
        lines.append(f" ip access-group {binding.acl_name} {binding.direction}")
        lines.append("!")
    return "\n".join(lines) if lines else "! no ip access-group is applied to any interface"


def render_nat(device: Device) -> str:
    inside = [i.name for i in device.interfaces if i.nat_side == NatSide.INSIDE]
    outside = [i.name for i in device.interfaces if i.nat_side == NatSide.OUTSIDE]
    lines = [
        "Total active translations: 0 (0 static, 0 dynamic; 0 extended)",
        "Peak translations: 0",
        "Outside interfaces:",
        f"  {', '.join(outside) if outside else '(none)'}",
        "Inside interfaces:",
        f"  {', '.join(inside) if inside else '(none)'}",
        "Hits: 0  Misses: 0",
        "Dynamic mappings:",
    ]
    for entry in device.nat_rules:
        if entry.kind == "static":
            lines.append(
                f"-- Inside Source static {entry.inside_local} {entry.inside_global}"
            )
            continue
        overload = f" interface {entry.out_interface} overload" if entry.out_interface else ""
        target = f" pool {entry.pool_name}" if entry.pool_name else ""
        lines.append(
            f"-- Inside Source access-list {entry.acl_name or '(none)'}{target}{overload}"
        )
    return "\n".join(lines)


def render_wireless(device: Device) -> str:
    lines = ["SSID Name                VLAN  Security     Guest  Client-Isolation"]
    for entry in device.ssids:
        lines.append(
            f"{entry.name:<24} {entry.vlan if entry.vlan is not None else '-':<5} "
            f"{entry.security or 'unset':<12} {'yes' if entry.is_guest else 'no':<6} "
            f"{entry.isolation_acl or 'none'}"
        )
    return "\n".join(lines)


def render_ipconfig(client: Host) -> str:
    adapter = "Wireless0 Connection:(default port)" if client.ssid else "FastEthernet0 Connection:(default port)"
    lines = [
        adapter,
        "",
        "   Connection-specific DNS Suffix..:",
        f"   IPv4 Address....................: {client.ip or '0.0.0.0'}",
        f"   Subnet Mask.....................: {client.mask or '0.0.0.0'}",
        f"   Default Gateway.................: {client.gateway or '0.0.0.0'}",
        "   DNS Servers.....................: "
        + (", ".join(client.dns_servers) if client.dns_servers else "(none configured)"),
    ]
    if client.dhcp_enabled:
        lines.append(
            "   DHCP Enabled....................: Yes"
            if client.ip
            else "   DHCP Enabled....................: Yes\n"
            "   DHCP request timed out — no DHCP server responded, address is unconfigured."
        )
    if client.ssid:
        lines.append(f"   SSID............................: {client.ssid}")
    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# case assembly
# --------------------------------------------------------------------------------------

_ROUTING_KINDS = (DeviceKind.ROUTER, DeviceKind.MULTILAYER_SWITCH, DeviceKind.FIREWALL)


def standard_outputs(lab: LabState) -> list[dict]:
    """Every capture a technician would take that the device prints from its own config."""
    outputs: list[dict] = []

    def add(device_name: str, command: str, text: str) -> None:
        outputs.append({"device": device_name, "command": command, "output": text})

    for device in lab.devices:
        if device.vlans:
            add(device.name, "show vlan brief", render_vlan_brief(device))
        if device.interfaces:
            add(device.name, "show ip interface brief", render_ip_int_brief(device))
        if device.kind in _ROUTING_KINDS and any(i.ip for i in device.interfaces):
            add(device.name, "show ip route", render_ip_route(device))
        if any(i.switchport_mode == SwitchportMode.TRUNK for i in device.interfaces):
            add(device.name, "show interfaces trunk", render_trunk(device))
        if device.dhcp_pools or any(i.helper_addresses for i in device.interfaces):
            add(device.name, "show running-config | section dhcp", render_dhcp(device))
        if device.acls:
            add(device.name, "show ip access-lists", render_acls(device))
            add(
                device.name,
                "show running-config | include access-group",
                render_acl_bindings(device),
            )
        if device.nat_rules:
            add(device.name, "show ip nat statistics", render_nat(device))
        if device.ssids:
            add(device.name, "show wlan summary", render_wireless(device))

    for client in lab.hosts:
        add(client.name, "ipconfig /all", render_ipconfig(client))

    return outputs


def ping(source: Host | str, target: str, *, ok: bool, note: str = "") -> dict:
    """A ping capture. Authored per case, because whether it replies is the symptom."""
    name = source if isinstance(source, str) else source.name
    if ok:
        body = (
            f"Pinging {target} with 32 bytes of data:\n\n"
            + "\n".join(f"Reply from {target}: bytes=32 time<1ms TTL=128" for _ in range(4))
            + f"\n\nPing statistics for {target}:\n"
            "    Packets: Sent = 4, Received = 4, Lost = 0 (0% loss),"
        )
    else:
        body = (
            f"Pinging {target} with 32 bytes of data:\n\n"
            + "\n".join([note or "Request timed out."] * 4)
            + f"\n\nPing statistics for {target}:\n"
            "    Packets: Sent = 4, Received = 0, Lost = 4 (100% loss)"
        )
    return {
        "device": name,
        "command": f"ping {target}",
        "output": f"{name}> ping {target}\n\n{body}",
    }


def capture(device_name: str, command: str, text: str) -> dict:
    return {"device": device_name, "command": command, "output": text}


def build_case(
    case_id: str,
    *,
    title: str,
    symptom: str,
    topology_note: str,
    concept: str,
    osi: str,
    severity: str,
    fault: str,
    keywords: Iterable[str],
    rules: Iterable[str],
    fixes: Iterable[str],
    lab: LabState,
    flows: Iterable[IntendedFlow] = (),
    extra: Iterable[dict] = (),
    security_relevant: bool = False,
) -> dict:
    """One complete case, with the derived captures merged in front of the authored ones.

    The assertions here are the same invariants ``tests/test_show_output_consistency.py``
    enforces. Failing at generation time makes a dataset defect impossible to commit.
    """
    outputs = list(extra) + standard_outputs(lab)

    seen: set[tuple[str, str]] = set()
    known = {d.name for d in lab.devices} | {h.name for h in lab.hosts}
    for item in outputs:
        key = (item["device"], item["command"])
        assert key not in seen, f"{case_id}: duplicate capture {key}"
        assert item["device"] in known, f"{case_id}: unknown device {item['device']}"
        seen.add(key)

    corpus = "\n".join(item["output"] for item in outputs)
    for device in lab.devices:
        for iface in device.interfaces:
            assert not iface.ip or iface.ip in corpus, (
                f"{case_id}: {device.name} {iface.name} address {iface.ip} appears in no output"
            )
    for client in lab.hosts:
        assert not client.ip or client.ip in corpus, (
            f"{case_id}: host {client.name} address {client.ip} appears in no output"
        )

    return {
        "case_id": case_id,
        "title": title,
        "symptom": symptom,
        "topology_note": topology_note,
        "show_outputs": outputs,
        "expected_fault": fault,
        "expected_root_cause_keywords": list(keywords),
        "osi_layer": osi,
        "concept_tag": concept,
        "severity": severity,
        "security_relevant": security_relevant,
        "lab_state": lab.model_dump(mode="json", exclude_defaults=True),
        "intended_flows": [f.model_dump(mode="json", exclude_defaults=True) for f in flows],
        "expected_rule_ids": list(rules),
        "expected_fix_steps": list(fixes),
        "source_label": "simulated-lab",
    }
