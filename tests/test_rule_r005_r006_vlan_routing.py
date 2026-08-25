"""R005 missing VLAN and R006 missing route — mandatory rules."""

from __future__ import annotations

from backend.app.models.enums import (
    AdminState,
    FlowExpect,
    OperState,
    RouteProtocol,
    Severity,
    SwitchportMode,
)
from backend.app.models.lab_state import IntendedFlow, Interface, Route, Vlan
from backend.app.rules.checks.routing import check_missing_route
from backend.app.rules.checks.vlan import check_missing_vlan
from backend.app.rules.engine import RuleContext, run_rules
from tests.conftest import clean_flows, clean_state, rule_ids


def ctx(state, flows=None) -> RuleContext:
    return RuleContext(state=state, intended_flows=flows or [])


# ---------------------------------------------------------------------------------
# R005 — missing VLAN
# ---------------------------------------------------------------------------------


def test_r005_detects_host_in_a_vlan_absent_from_the_switch():
    state = clean_state()
    state.host("PC-B").vlan = 30  # VLAN 30 is not in SW1's database

    findings = check_missing_vlan(ctx(state))

    assert len(findings) == 1
    assert findings[0].rule_id == "R005"
    assert "VLAN 30 does not exist" in findings[0].message
    assert findings[0].suggested_mutation == {
        "type": "add_vlan",
        "device": "SW1",
        "vlan_id": 30,
        "name": "VLAN30",
    }


def test_r005_detects_access_port_in_a_nonexistent_vlan():
    state = clean_state()
    state.device("SW1").interface("GigabitEthernet0/2").vlan = 40

    findings = check_missing_vlan(ctx(state))

    port_findings = [f for f in findings if "access port" in f.message]
    assert len(port_findings) == 1
    assert "VLAN 40" in port_findings[0].message


def test_r005_detects_svi_for_a_vlan_that_was_never_created():
    """The classic Packet Tracer trap: interface Vlan30 exists, 'vlan 30' does not."""
    state = clean_state()
    state.device("SW1").interfaces.append(
        Interface(
            name="Vlan30",
            ip="192.168.30.1",
            mask="255.255.255.0",
            is_svi=True,
            vlan=30,
        )
    )

    findings = check_missing_vlan(ctx(state))

    svi_findings = [f for f in findings if "SVI" in f.message]
    assert len(svi_findings) == 1
    assert svi_findings[0].severity == Severity.CRITICAL
    assert "never created" in svi_findings[0].message


def test_r005_lists_the_vlans_that_do_exist_as_evidence():
    state = clean_state()
    state.host("PC-B").vlan = 30

    finding = check_missing_vlan(ctx(state))[0]
    vlan_db_evidence = [e for e in finding.evidence if "vlan database" in e.source]

    assert len(vlan_db_evidence) == 1
    assert "10 (SALES)" in vlan_db_evidence[0].detail
    assert "20 (HR)" in vlan_db_evidence[0].detail


def test_r005_no_false_positive_on_clean_state():
    assert check_missing_vlan(ctx(clean_state())) == []


def test_r005_ignores_trunk_ports():
    """A trunk carrying VLANs is not an access-VLAN assignment; R008 covers trunks."""
    state = clean_state()
    iface = state.device("SW1").interface("GigabitEthernet0/2")
    iface.switchport_mode = SwitchportMode.TRUNK
    iface.vlan = 99
    iface.allowed_vlans = [10, 20, 99]

    assert check_missing_vlan(ctx(state)) == []


# ---------------------------------------------------------------------------------
# R006 — missing route
# ---------------------------------------------------------------------------------


def test_r006_detects_no_route_to_the_destination():
    """Removing the Vlan20 SVI leaves SW1 with no path to PC-B's subnet."""
    state = clean_state()
    sw1 = state.device("SW1")
    sw1.interfaces = [i for i in sw1.interfaces if i.name != "Vlan20"]

    flows = [IntendedFlow(src="PC-A", dst="PC-B", expect=FlowExpect.PERMIT)]
    findings = check_missing_route(ctx(state, flows))

    assert len(findings) == 1
    assert findings[0].rule_id == "R006"
    assert "no route to 192.168.20.0/24" in findings[0].message


def test_r006_treats_a_down_interface_as_no_connected_route():
    state = clean_state()
    vlan20 = state.device("SW1").interface("Vlan20")
    vlan20.admin_state = AdminState.SHUTDOWN
    vlan20.oper_state = OperState.DOWN

    flows = [IntendedFlow(src="PC-A", dst="PC-B", expect=FlowExpect.PERMIT)]
    findings = check_missing_route(ctx(state, flows))

    assert len(findings) == 1
    assert "no route" in findings[0].message


def test_r006_accepts_a_default_route():
    state = clean_state()
    sw1 = state.device("SW1")
    sw1.interfaces = [i for i in sw1.interfaces if i.name != "Vlan20"]
    sw1.routes.append(
        Route(prefix="0.0.0.0", mask="0.0.0.0", next_hop="10.0.0.1", protocol=RouteProtocol.STATIC)
    )

    flows = [IntendedFlow(src="PC-A", dst="PC-B", expect=FlowExpect.PERMIT)]

    assert check_missing_route(ctx(state, flows)) == []


def test_r006_accepts_a_matching_static_route():
    state = clean_state()
    sw1 = state.device("SW1")
    sw1.interfaces = [i for i in sw1.interfaces if i.name != "Vlan20"]
    sw1.routes.append(
        Route(
            prefix="192.168.20.0",
            mask="255.255.255.0",
            next_hop="10.0.0.1",
            protocol=RouteProtocol.STATIC,
        )
    )

    flows = [IntendedFlow(src="PC-A", dst="PC-B", expect=FlowExpect.PERMIT)]

    assert check_missing_route(ctx(state, flows)) == []


def test_r006_detects_ip_routing_disabled():
    state = clean_state()
    state.device("SW1").ip_routing_enabled = False

    findings = check_missing_route(ctx(state, clean_flows()))

    assert len(findings) == 1  # reported once for the device, not once per flow
    assert "IP routing is disabled" in findings[0].message
    assert findings[0].severity == Severity.CRITICAL
    assert findings[0].suggested_mutation == {"type": "enable_ip_routing", "device": "SW1"}


def test_r006_ignores_same_subnet_flows():
    """Two hosts on one subnet involve no routing decision."""
    state = clean_state()
    state.host("PC-B").ip = "192.168.10.20"
    state.host("PC-B").gateway = "192.168.10.1"
    state.host("PC-B").vlan = 10

    flows = [IntendedFlow(src="PC-A", dst="PC-B", expect=FlowExpect.PERMIT)]

    assert check_missing_route(ctx(state, flows)) == []


def test_r006_ignores_flows_that_are_meant_to_be_denied():
    state = clean_state()
    sw1 = state.device("SW1")
    sw1.interfaces = [i for i in sw1.interfaces if i.name != "Vlan20"]

    flows = [IntendedFlow(src="PC-A", dst="PC-B", expect=FlowExpect.DENY)]

    assert check_missing_route(ctx(state, flows)) == []


def test_r006_needs_intended_flows_to_say_anything():
    """No declared intent means no decidable question, so no finding."""
    state = clean_state()
    sw1 = state.device("SW1")
    sw1.interfaces = [i for i in sw1.interfaces if i.name != "Vlan20"]

    assert check_missing_route(ctx(state, [])) == []


def test_r006_no_false_positive_on_clean_state():
    assert check_missing_route(ctx(clean_state(), clean_flows())) == []


# ---------------------------------------------------------------------------------
# Integration — the CASE-001 fault pattern
# ---------------------------------------------------------------------------------


def test_missing_vlan_plus_shutdown_svi_fires_r004_r005_and_r006():
    """This is the compound fault CASE-001 encodes, built from scratch here so the
    rule behaviour is pinned independently of the dataset."""
    state = clean_state()
    sw1 = state.device("SW1")

    # A VLAN 30 SVI that is shut down, with VLAN 30 absent from the database.
    sw1.interfaces.append(
        Interface(
            name="Vlan30",
            ip="192.168.30.1",
            mask="255.255.255.0",
            is_svi=True,
            vlan=30,
            admin_state=AdminState.SHUTDOWN,
            oper_state=OperState.DOWN,
        )
    )
    sw1.interfaces.append(
        Interface(
            name="GigabitEthernet0/5",
            switchport_mode=SwitchportMode.ACCESS,
            vlan=30,
        )
    )
    state.hosts.append(
        state.hosts[0].model_copy(
            update={
                "name": "SRV-FILES",
                "ip": "192.168.30.10",
                "gateway": "192.168.30.1",
                "vlan": 30,
                "connected_interface": "GigabitEthernet0/5",
            }
        )
    )

    flows = [IntendedFlow(src="PC-A", dst="SRV-FILES", expect=FlowExpect.PERMIT)]
    fired = rule_ids(run_rules(state, flows))

    assert fired == ["R004", "R005", "R006"]
