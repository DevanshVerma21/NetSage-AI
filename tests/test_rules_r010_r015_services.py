"""R010 DHCP, R011 DNS, R012 ACL, R013 NAT, R014 wireless, R015 SVI.

Every rule gets at least one positive test and one negative ("must not false-positive")
test. R010, R012, R013 and R014 carry extra sub-type tests because each of them decides
several distinct faults, and R012/R014 additionally decide against declared intent.
"""

from __future__ import annotations

from backend.app.models.enums import (
    AclAction,
    AdminState,
    DeviceKind,
    FlowExpect,
    LinkMode,
    NatSide,
    OperState,
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
    Ssid,
    Vlan,
)
from backend.app.rules.checks.acl import check_acl_blocks_flow
from backend.app.rules.checks.dhcp import check_dhcp_configuration
from backend.app.rules.checks.dns import check_dns_configuration
from backend.app.rules.checks.nat import check_nat_configuration
from backend.app.rules.checks.svi import check_svi_state
from backend.app.rules.checks.wireless import check_wireless_configuration
from backend.app.rules.engine import RuleContext, run_rules
from tests.conftest import clean_flows, clean_state, rule_ids

_MASK = "255.255.255.0"


def ctx(state, flows=None) -> RuleContext:
    return RuleContext(state=state, intended_flows=flows or [])


def healthy_pool() -> DhcpPool:
    return DhcpPool(
        name="VLAN10",
        network="192.168.10.0",
        mask=_MASK,
        default_router="192.168.10.1",
    )


# ---------------------------------------------------------------------------------
# R010 — DHCP configuration fault
# ---------------------------------------------------------------------------------


def test_r010_detects_a_pool_for_a_network_the_device_is_not_attached_to():
    state = clean_state()
    pool = healthy_pool()
    pool.network = "192.168.99.0"
    pool.default_router = "192.168.99.1"
    state.device("SW1").dhcp_pools.append(pool)

    findings = check_dhcp_configuration(ctx(state))

    assert {f.rule_id for f in findings} == {"R010"}
    assert any("not a subnet SW1 is attached to" in f.message for f in findings)


def test_r010_detects_a_default_router_outside_the_pool_network():
    state = clean_state()
    pool = healthy_pool()
    pool.default_router = "192.168.11.1"
    state.device("SW1").dhcp_pools.append(pool)

    messages = [f.message for f in check_dhcp_configuration(ctx(state))]

    assert any("outside the pool's own network" in m for m in messages)


def test_r010_detects_an_excluded_address_outside_the_pool_network():
    state = clean_state()
    pool = healthy_pool()
    pool.excluded = ["192.168.1.1"]
    state.device("SW1").dhcp_pools.append(pool)

    messages = [f.message for f in check_dhcp_configuration(ctx(state))]

    assert any("not part of its network" in m for m in messages)


def test_r010_detects_a_dns_server_no_device_owns():
    state = clean_state()
    pool = healthy_pool()
    pool.dns_servers = ["192.168.10.253"]
    state.device("SW1").dhcp_pools.append(pool)

    messages = [f.message for f in check_dhcp_configuration(ctx(state))]

    assert any("no device or host in the topology has that address" in m for m in messages)


def test_r010_detects_a_dhcp_client_with_no_pool_and_no_relay():
    state = clean_state()
    client = state.host("PC-A")
    client.dhcp_enabled = True
    client.ip = None

    findings = check_dhcp_configuration(ctx(state))

    assert [f.rule_id for f in findings] == ["R010"]
    assert "no ip helper-address" in findings[0].message


def test_r010_does_not_fire_on_a_correct_pool():
    state = clean_state()
    state.device("SW1").dhcp_pools.append(healthy_pool())

    assert check_dhcp_configuration(ctx(state)) == []


def test_r010_does_not_fire_when_no_dhcp_is_configured_at_all():
    assert check_dhcp_configuration(ctx(clean_state())) == []
    assert "R010" not in rule_ids(run_rules(clean_state(), clean_flows()))


# ---------------------------------------------------------------------------------
# R011 — DNS configuration or reachability fault
# ---------------------------------------------------------------------------------


def dns_flow() -> list[IntendedFlow]:
    return [IntendedFlow(src="PC-A", dst="PC-B", proto="dns", port=53)]


def test_r011_detects_a_client_with_no_resolver():
    state = clean_state()
    state.host("PC-B").dns_servers = []

    findings = check_dns_configuration(ctx(state, dns_flow()))

    assert [f.rule_id for f in findings] == ["R011"]
    assert "no DNS server configured" in findings[0].message


def test_r011_detects_a_client_pointed_at_the_wrong_resolver():
    state = clean_state()
    state.host("PC-A").dns_servers = ["192.168.10.1"]  # the gateway, not PC-B

    messages = [f.message for f in check_dns_configuration(ctx(state, dns_flow()))]

    assert any("resolver it is supposed to use is PC-B" in m for m in messages)


def test_r011_detects_a_resolver_address_nothing_owns():
    state = clean_state()
    state.host("PC-A").dns_servers = ["10.10.10.53"]

    messages = [f.message for f in check_dns_configuration(ctx(state, dns_flow()))]

    assert any("no device or host in the topology has that address" in m for m in messages)


def test_r011_detects_a_resolver_whose_access_port_is_down():
    state = clean_state()
    state.host("PC-A").dns_servers = ["192.168.20.10"]
    port = state.device("SW1").interface("GigabitEthernet0/2")
    port.admin_state = AdminState.SHUTDOWN
    port.oper_state = OperState.DOWN

    messages = [f.message for f in check_dns_configuration(ctx(state, dns_flow()))]

    assert any("the DNS service is unreachable" in m for m in messages)


def test_r011_does_not_fire_when_the_resolver_is_configured_correctly():
    state = clean_state()
    state.host("PC-A").dns_servers = ["192.168.20.10"]

    assert check_dns_configuration(ctx(state, dns_flow())) == []


def test_r011_stays_silent_without_a_declared_dns_flow():
    """No declared intent means there is no deterministic resolver to check against."""
    state = clean_state()
    state.host("PC-A").dns_servers = []

    assert check_dns_configuration(ctx(state, clean_flows())) == []
    assert "R011" not in rule_ids(run_rules(clean_state(), clean_flows()))


# ---------------------------------------------------------------------------------
# R012 — an ACL blocks (or fails to block) an intended flow
# ---------------------------------------------------------------------------------


def smb_flow(expect=FlowExpect.PERMIT) -> list[IntendedFlow]:
    return [IntendedFlow(src="PC-A", dst="PC-B", proto="tcp", port=445, expect=expect)]


def _bind_acl(state, acl: Acl, interface: str, direction: str):
    device = state.device("SW1")
    device.acls.append(acl)
    device.acl_bindings.append(
        AclBinding(acl_name=acl.name, interface=interface, direction=direction)
    )
    return state


def _deny_smb() -> Acl:
    return Acl(
        name="BLOCK-SMB",
        entries=[
            AclEntry(seq=10, action=AclAction.DENY, protocol="tcp", src="192.168.10.0",
                     src_wildcard="0.0.0.255", dst="192.168.20.10", port_op="eq", port=445),
            AclEntry(seq=20, action=AclAction.PERMIT),
        ],
    )


def test_r012_detects_an_explicit_deny_of_an_intended_flow():
    state = _bind_acl(clean_state(), _deny_smb(), "Vlan10", "in")

    findings = check_acl_blocks_flow(ctx(state, smb_flow()))

    assert [f.rule_id for f in findings] == ["R012"]
    assert "denies PC-A -> PC-B (tcp/445)" in findings[0].message


def test_r012_detects_traffic_that_dies_on_the_implicit_deny():
    web_only = Acl(
        name="WEB-ONLY",
        entries=[
            AclEntry(seq=10, action=AclAction.PERMIT, protocol="tcp", src="192.168.10.0",
                     src_wildcard="0.0.0.255", port_op="eq", port=443),
        ],
    )
    state = _bind_acl(clean_state(), web_only, "Vlan10", "in")

    findings = check_acl_blocks_flow(ctx(state, smb_flow()))

    assert [f.rule_id for f in findings] == ["R012"]
    assert "implicit deny at the end of the list" in findings[0].message


def test_r012_detects_a_filter_bound_where_the_traffic_never_meets_it():
    """A deny-intent flow that nothing stops: the list is on the wrong interface."""
    state = _bind_acl(clean_state(), _deny_smb(), "Vlan20", "in")

    findings = check_acl_blocks_flow(ctx(state, smb_flow(FlowExpect.DENY)))

    assert [f.rule_id for f in findings] == ["R012"]
    assert "is supposed to be denied" in findings[0].message


def test_r012_does_not_fire_when_the_list_matches_the_declared_intent():
    permit_smb = Acl(
        name="PERMIT-SMB",
        entries=[
            AclEntry(seq=10, action=AclAction.PERMIT, protocol="tcp", src="192.168.10.0",
                     src_wildcard="0.0.0.255", dst="192.168.20.10", port_op="eq", port=445),
            AclEntry(seq=20, action=AclAction.PERMIT),
        ],
    )
    state = _bind_acl(clean_state(), permit_smb, "Vlan10", "in")

    assert check_acl_blocks_flow(ctx(state, smb_flow())) == []


def test_r012_does_not_fire_on_a_restrictive_list_with_no_contradicted_intent():
    """A deny is only a fault against declared intent, never because it looks strict."""
    state = _bind_acl(clean_state(), _deny_smb(), "Vlan10", "in")

    assert check_acl_blocks_flow(ctx(state, clean_flows())) == []
    assert "R012" not in rule_ids(run_rules(clean_state(), clean_flows()))


# ---------------------------------------------------------------------------------
# R013 — NAT configuration fault
# ---------------------------------------------------------------------------------


def nat_state(*, inside=True, outside=True, acls=None, rules=None) -> LabState:
    edge = Device(
        name="R-NAT",
        kind=DeviceKind.ROUTER,
        interfaces=[
            Interface(name="GigabitEthernet0/0", ip="192.168.240.1", mask=_MASK,
                      nat_side=NatSide.INSIDE if inside else None),
            Interface(name="GigabitEthernet0/1", ip="203.0.113.2", mask="255.255.255.252",
                      nat_side=NatSide.OUTSIDE if outside else None),
        ],
        acls=list(acls or []),
        nat_rules=list(rules or []),
    )
    return LabState(
        devices=[edge],
        hosts=[
            Host(name="PC-INSIDE", ip="192.168.240.20", mask=_MASK, gateway="192.168.240.1",
                 connected_device="R-NAT", connected_interface="GigabitEthernet0/0")
        ],
        links=[
            Link(a_device="PC-INSIDE", a_interface="FastEthernet0", b_device="R-NAT",
                 b_interface="GigabitEthernet0/0", mode=LinkMode.ROUTED)
        ],
    )


def nat_acl(network: str = "192.168.240.0") -> Acl:
    return Acl(
        name="NAT-INSIDE",
        entries=[
            AclEntry(seq=10, action=AclAction.PERMIT, src=network, src_wildcard="0.0.0.255")
        ],
    )


def overload_rule() -> NatRule:
    return NatRule(kind="overload", acl_name="NAT-INSIDE",
                   out_interface="GigabitEthernet0/1")


def test_r013_detects_a_missing_outside_designation():
    state = nat_state(outside=False, acls=[nat_acl()], rules=[overload_rule()])

    findings = check_nat_configuration(ctx(state))

    assert [f.rule_id for f in findings] == ["R013"]
    assert "ip nat outside" in findings[0].message


def test_r013_detects_a_rule_naming_an_access_list_that_does_not_exist():
    state = nat_state(acls=[], rules=[overload_rule()])

    findings = check_nat_configuration(ctx(state))

    assert [f.rule_id for f in findings] == ["R013"]
    assert "no such access list exists" in findings[0].message


def test_r013_detects_a_dynamic_rule_with_neither_pool_nor_overload():
    state = nat_state(acls=[nat_acl()], rules=[NatRule(kind="dynamic")])

    findings = check_nat_configuration(ctx(state))

    assert [f.rule_id for f in findings] == ["R013"]
    assert "no global address to translate into" in findings[0].message


def test_r013_detects_an_acl_matching_a_network_no_inside_interface_serves():
    state = nat_state(acls=[nat_acl("192.168.24.0")], rules=[overload_rule()])

    findings = check_nat_configuration(ctx(state))

    assert [f.rule_id for f in findings] == ["R013"]
    assert "on none of its inside interfaces" in findings[0].message


def test_r013_does_not_fire_on_a_complete_overload_configuration():
    state = nat_state(acls=[nat_acl()], rules=[overload_rule()])

    assert check_nat_configuration(ctx(state)) == []


def test_r013_stays_silent_on_a_device_that_does_not_translate():
    assert check_nat_configuration(ctx(clean_state())) == []
    assert "R013" not in rule_ids(run_rules(clean_state(), clean_flows()))


# ---------------------------------------------------------------------------------
# R014 — wireless guest isolation and SSID faults
# ---------------------------------------------------------------------------------


def wifi_state(*, ssid_name="GUEST-WIFI", ssid_vlan=50, is_guest=True, isolation=None,
               client_ssid="GUEST-WIFI", client_vlan=50, uplink_down=False,
               wired_in_guest_vlan=False) -> LabState:
    admin = AdminState.SHUTDOWN if uplink_down else AdminState.UP
    oper = OperState.DOWN if uplink_down else OperState.UP
    ap = Device(
        name="AP-1",
        kind=DeviceKind.ACCESS_POINT,
        ip_routing_enabled=False,
        vlans=[Vlan(vlan_id=20, name="INTERNAL"), Vlan(vlan_id=50, name="GUEST")],
        interfaces=[
            Interface(name="GigabitEthernet0/1", switchport_mode=SwitchportMode.TRUNK,
                      allowed_vlans=[20, 50], native_vlan=1,
                      admin_state=admin, oper_state=oper),
        ],
        ssids=[Ssid(name=ssid_name, vlan=ssid_vlan, is_guest=is_guest,
                    isolation_acl=isolation, security="wpa2-psk")],
    )
    sw = Device(
        name="SW-WIFI",
        kind=DeviceKind.MULTILAYER_SWITCH,
        vlans=[Vlan(vlan_id=20, name="INTERNAL"), Vlan(vlan_id=50, name="GUEST")],
        interfaces=[
            Interface(name="GigabitEthernet0/1", switchport_mode=SwitchportMode.ACCESS,
                      vlan=20 if not wired_in_guest_vlan else 50),
            Interface(name="Vlan20", ip="192.168.20.1", mask=_MASK, is_svi=True, vlan=20),
            Interface(name="Vlan50", ip="192.168.50.1", mask=_MASK, is_svi=True, vlan=50),
            Interface(name="GigabitEthernet0/24", switchport_mode=SwitchportMode.TRUNK,
                      allowed_vlans=[20, 50], native_vlan=1),
        ],
    )
    internal_vlan = 50 if wired_in_guest_vlan else 20
    return LabState(
        devices=[ap, sw],
        hosts=[
            Host(name="PC-GUEST", ip="192.168.50.30", mask=_MASK, gateway="192.168.50.1",
                 vlan=client_vlan, connected_device="AP-1", connected_interface="Dot11Radio0",
                 ssid=client_ssid),
            Host(name="SRV-HR", ip=f"192.168.{internal_vlan}.10", mask=_MASK,
                 gateway=f"192.168.{internal_vlan}.1", vlan=internal_vlan,
                 connected_device="SW-WIFI", connected_interface="GigabitEthernet0/1"),
        ],
        links=[
            Link(a_device="AP-1", a_interface="GigabitEthernet0/1", b_device="SW-WIFI",
                 b_interface="GigabitEthernet0/24", mode=LinkMode.TRUNK,
                 allowed_vlans=[20, 50], native_vlan=1),
            Link(a_device="SRV-HR", a_interface="FastEthernet0", b_device="SW-WIFI",
                 b_interface="GigabitEthernet0/1", mode=LinkMode.ACCESS,
                 access_vlan=internal_vlan),
        ],
    )


def guest_deny_flow() -> list[IntendedFlow]:
    return [IntendedFlow(src="PC-GUEST", dst="SRV-HR", proto="tcp", port=443,
                         expect=FlowExpect.DENY, note="Guests must not reach HR")]


def test_r014_detects_a_guest_ssid_with_no_isolation_against_a_deny_intent():
    findings = check_wireless_configuration(ctx(wifi_state(), guest_deny_flow()))

    assert [f.rule_id for f in findings] == ["R014"]
    assert "no client isolation" in findings[0].message


def test_r014_detects_an_isolation_list_that_does_not_exist():
    state = wifi_state(isolation="GUEST-ISO")

    findings = check_wireless_configuration(ctx(state, guest_deny_flow()))

    assert [f.rule_id for f in findings] == ["R014"]
    assert "does not exist on AP-1" in findings[0].message


def test_r014_detects_a_client_joined_to_an_ssid_nothing_broadcasts():
    state = wifi_state(client_ssid="CORP-WIFI", is_guest=False, ssid_name="CORP_WIFI")

    findings = check_wireless_configuration(ctx(state))

    assert [f.rule_id for f in findings] == ["R014"]
    assert "never associates" in findings[0].message


def test_r014_detects_an_ssid_mapped_to_the_wrong_vlan():
    state = wifi_state(is_guest=False, ssid_vlan=60)

    messages = [f.message for f in check_wireless_configuration(ctx(state))]

    assert any("maps to VLAN 60" in m for m in messages)


def test_r014_detects_a_guest_ssid_sharing_a_vlan_with_wired_internal_hosts():
    state = wifi_state(wired_in_guest_vlan=True)

    messages = [f.message for f in check_wireless_configuration(ctx(state))]

    assert any("same VLAN as internal hosts" in m for m in messages)


def test_r014_detects_an_access_point_whose_only_uplink_is_down():
    state = wifi_state(is_guest=False, uplink_down=True)

    messages = [f.message for f in check_wireless_configuration(ctx(state))]

    assert any("Every uplink on AP-1 is down" in m for m in messages)


def test_r014_does_not_fire_when_isolation_is_enforced():
    state = wifi_state(isolation="GUEST-ISO")
    state.device("AP-1").acls.append(
        Acl(name="GUEST-ISO", entries=[AclEntry(seq=10, action=AclAction.DENY)])
    )

    assert check_wireless_configuration(ctx(state, guest_deny_flow())) == []


def test_r014_stays_silent_on_a_topology_with_no_wireless():
    assert check_wireless_configuration(ctx(clean_state(), clean_flows())) == []
    assert "R014" not in rule_ids(run_rules(clean_state(), clean_flows()))


# ---------------------------------------------------------------------------------
# R015 — SVI shutdown or missing
# ---------------------------------------------------------------------------------


def test_r015_detects_an_administratively_shut_svi():
    state = clean_state()
    svi = state.device("SW1").interface("Vlan10")
    svi.admin_state = AdminState.SHUTDOWN
    svi.oper_state = OperState.DOWN

    findings = check_svi_state(ctx(state))

    assert [f.rule_id for f in findings] == ["R015"]
    assert "administratively shut down" in findings[0].message
    assert findings[0].suggested_mutation == {
        "type": "set_interface_admin_state",
        "device": "SW1",
        "interface": "Vlan10",
        "admin_state": "up",
    }


def test_r015_detects_a_line_protocol_down_svi():
    state = clean_state()
    state.device("SW1").interface("Vlan10").oper_state = OperState.DOWN

    findings = check_svi_state(ctx(state))

    assert [f.rule_id for f in findings] == ["R015"]
    assert "line-protocol down" in findings[0].message


def test_r015_detects_a_populated_vlan_with_no_svi_on_a_routing_switch():
    state = clean_state()
    device = state.device("SW1")
    device.interfaces = [i for i in device.interfaces if i.name != "Vlan20"]

    findings = check_svi_state(ctx(state))

    assert [f.rule_id for f in findings] == ["R015"]
    assert "no SVI for VLAN 20" in findings[0].message


def test_r015_does_not_fire_for_a_vlan_with_no_members():
    state = clean_state()
    device = state.device("SW1")
    device.vlans.append(Vlan(vlan_id=99, name="SPARE"))

    assert check_svi_state(ctx(state)) == []


def test_r015_does_not_fire_on_a_layer_two_switch_without_svis():
    """On a pure Layer 2 switch, having no SVI for a VLAN is normal."""
    state = clean_state()
    device = state.device("SW1")
    device.kind = DeviceKind.SWITCH
    device.ip_routing_enabled = False
    device.interfaces = [i for i in device.interfaces if not i.is_svi]

    assert check_svi_state(ctx(state)) == []


def test_r015_does_not_fire_on_the_healthy_topology():
    assert check_svi_state(ctx(clean_state())) == []
    assert "R015" not in rule_ids(run_rules(clean_state(), clean_flows()))
