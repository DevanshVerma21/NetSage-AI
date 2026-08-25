"""R003 gateway mismatch and R004 interface down — mandatory rules."""

from __future__ import annotations

from backend.app.models.enums import AdminState, OperState, Severity
from backend.app.models.lab_state import Interface
from backend.app.rules.checks.gateway import check_gateway_mismatch
from backend.app.rules.checks.interface import check_interface_down
from backend.app.rules.engine import RuleContext, run_rules
from tests.conftest import clean_flows, clean_state, rule_ids


def ctx(state, flows=None) -> RuleContext:
    return RuleContext(state=state, intended_flows=flows or [])


# ---------------------------------------------------------------------------------
# R003 — gateway mismatch
# ---------------------------------------------------------------------------------


def test_r003_detects_gateway_outside_the_host_subnet():
    state = clean_state()
    state.host("PC-A").gateway = "192.168.20.1"  # PC-A is in 192.168.10.0/24

    findings = check_gateway_mismatch(ctx(state))

    assert len(findings) == 1
    assert findings[0].rule_id == "R003"
    assert "outside its own subnet" in findings[0].message
    assert "192.168.10.0/24" in findings[0].message


def test_r003_proposes_the_correct_in_subnet_gateway():
    state = clean_state()
    state.host("PC-A").gateway = "192.168.20.1"

    finding = check_gateway_mismatch(ctx(state))[0]

    assert finding.suggested_mutation == {
        "type": "set_host_gateway",
        "host": "PC-A",
        "gateway": "192.168.10.1",
    }


def test_r003_detects_gateway_that_no_device_owns():
    state = clean_state()
    state.host("PC-A").gateway = "192.168.10.254"  # in-subnet but nothing owns it

    findings = check_gateway_mismatch(ctx(state))

    assert len(findings) == 1
    assert "no Layer 3 interface" in findings[0].message


def test_r003_detects_host_with_no_gateway_at_all():
    state = clean_state()
    state.host("PC-A").gateway = None

    findings = check_gateway_mismatch(ctx(state))

    assert len(findings) == 1
    assert "no default gateway" in findings[0].message


def test_r003_reports_out_of_subnet_gateway_only_once():
    """An out-of-subnet gateway must not also be reported as 'unowned'."""
    state = clean_state()
    state.host("PC-A").gateway = "10.99.99.99"

    findings = check_gateway_mismatch(ctx(state))

    assert len(findings) == 1
    assert "outside its own subnet" in findings[0].message


def test_r003_no_false_positive_on_clean_state():
    assert check_gateway_mismatch(ctx(clean_state())) == []


# ---------------------------------------------------------------------------------
# R004 — interface down
# ---------------------------------------------------------------------------------


def test_r004_detects_administratively_down_svi():
    state = clean_state()
    state.device("SW1").interface("Vlan20").admin_state = AdminState.SHUTDOWN
    state.device("SW1").interface("Vlan20").oper_state = OperState.DOWN

    findings = check_interface_down(ctx(state))

    assert len(findings) == 1
    assert findings[0].rule_id == "R004"
    assert findings[0].severity == Severity.CRITICAL
    assert "administratively down" in findings[0].message
    assert findings[0].suggested_mutation == {
        "type": "set_interface_admin_state",
        "device": "SW1",
        "interface": "Vlan20",
        "admin_state": "up",
    }


def test_r004_detects_operationally_down_access_port_on_a_link():
    state = clean_state()
    state.device("SW1").interface("GigabitEthernet0/1").oper_state = OperState.DOWN

    findings = check_interface_down(ctx(state))

    assert len(findings) == 1
    assert "down/down" in findings[0].message
    # A line-protocol failure has no config mutation that would fix it.
    assert findings[0].suggested_mutation is None


def test_r004_ignores_unused_unconnected_ports():
    """A spare port being down is housekeeping, not a fault — this is the main
    false-positive risk for this rule."""
    state = clean_state()
    state.device("SW1").interfaces.append(
        Interface(
            name="GigabitEthernet0/24",
            admin_state=AdminState.SHUTDOWN,
            oper_state=OperState.DOWN,
        )
    )

    assert check_interface_down(ctx(state)) == []


def test_r004_reports_down_interface_that_carries_an_ip():
    state = clean_state()
    state.device("SW1").interface("Vlan10").admin_state = AdminState.SHUTDOWN
    state.device("SW1").interface("Vlan10").oper_state = OperState.DOWN

    finding = check_interface_down(ctx(state))[0]

    assert "192.168.10.1" in finding.message
    assert "unreachable" in finding.message


def test_r004_no_false_positive_on_clean_state():
    assert check_interface_down(ctx(clean_state())) == []


# ---------------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------------


def test_engine_reports_r003_and_r004_together():
    state = clean_state()
    state.host("PC-A").gateway = "192.168.99.1"
    state.device("SW1").interface("Vlan20").admin_state = AdminState.SHUTDOWN
    state.device("SW1").interface("Vlan20").oper_state = OperState.DOWN

    fired = rule_ids(run_rules(state, clean_flows()))

    assert "R003" in fired
    assert "R004" in fired
