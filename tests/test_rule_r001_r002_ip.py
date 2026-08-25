"""R001 duplicate IP and R002 wrong subnet mask — mandatory rules.

Each rule gets positive tests (the fault is detected) and negative tests (no
false positive on a healthy topology).
"""

from __future__ import annotations

from backend.app.models.enums import Severity
from backend.app.rules.checks.ip_addressing import check_duplicate_ip, check_wrong_subnet_mask
from backend.app.rules.engine import RuleContext, run_rules
from tests.conftest import clean_flows, clean_state, rule_ids


def ctx(state, flows=None) -> RuleContext:
    return RuleContext(state=state, intended_flows=flows or [])


# ---------------------------------------------------------------------------------
# R001 — duplicate IP
# ---------------------------------------------------------------------------------


def test_r001_detects_duplicate_ip_between_two_hosts():
    state = clean_state()
    state.host("PC-B").ip = "192.168.10.10"  # already used by PC-A

    findings = check_duplicate_ip(ctx(state))

    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule_id == "R001"
    assert finding.severity == Severity.CRITICAL
    assert "192.168.10.10" in finding.message
    assert set(finding.affected) == {"PC-A", "PC-B"}


def test_r001_detects_host_colliding_with_an_svi():
    state = clean_state()
    state.host("PC-A").ip = "192.168.10.1"  # the Vlan10 gateway address

    findings = check_duplicate_ip(ctx(state))

    assert len(findings) == 1
    assert "SW1 Vlan10" in findings[0].affected
    assert "PC-A" in findings[0].affected


def test_r001_reports_three_way_collision_as_one_finding():
    state = clean_state()
    state.host("PC-A").ip = "192.168.20.1"
    state.host("PC-B").ip = "192.168.20.1"

    findings = check_duplicate_ip(ctx(state))

    assert len(findings) == 1
    assert len(findings[0].evidence) == 3  # PC-A, PC-B and the SVI


def test_r001_no_false_positive_on_clean_state():
    assert check_duplicate_ip(ctx(clean_state())) == []


def test_r001_ignores_interfaces_without_addresses():
    """Several access ports share 'no ip address'. That is not a duplicate."""
    state = clean_state()
    assert check_duplicate_ip(ctx(state)) == []


# ---------------------------------------------------------------------------------
# R002 — wrong subnet mask
# ---------------------------------------------------------------------------------


def test_r002_detects_non_contiguous_mask_on_an_interface():
    state = clean_state()
    state.device("SW1").interface("Vlan20").mask = "255.255.0.255"

    findings = check_wrong_subnet_mask(ctx(state))

    invalid = [f for f in findings if "non-contiguous" in f.message]
    assert len(invalid) == 1
    assert invalid[0].severity == Severity.CRITICAL
    assert "255.255.0.255" in invalid[0].message


def test_r002_detects_non_contiguous_mask_on_a_host():
    state = clean_state()
    state.host("PC-A").mask = "255.0.255.0"

    findings = check_wrong_subnet_mask(ctx(state))

    invalid = [f for f in findings if "PC-A" in f.affected and "non-contiguous" in f.message]
    assert len(invalid) == 1


def test_r002_detects_host_mask_disagreeing_with_gateway_mask():
    state = clean_state()
    state.host("PC-A").mask = "255.255.0.0"  # gateway Vlan10 is /24

    findings = check_wrong_subnet_mask(ctx(state))

    mismatches = [f for f in findings if "disagree" in f.message]
    assert len(mismatches) == 1
    assert "/16" in mismatches[0].message and "/24" in mismatches[0].message
    assert mismatches[0].suggested_mutation == {
        "type": "set_host_mask",
        "host": "PC-A",
        "mask": "255.255.255.0",
    }


def test_r002_detects_prefix_too_long_for_a_lan():
    state = clean_state()
    state.host("PC-A").mask = "255.255.255.255"
    state.device("SW1").interface("Vlan10").mask = "255.255.255.255"  # keep (b) quiet

    findings = check_wrong_subnet_mask(ctx(state))

    too_long = [f for f in findings if "/32" in f.message]
    assert len(too_long) == 1


def test_r002_does_not_report_mask_mismatch_when_gateway_is_unowned():
    """An unowned gateway is R003's finding, not a mask fault."""
    state = clean_state()
    state.host("PC-A").gateway = "192.168.10.254"  # nothing owns this
    state.host("PC-A").mask = "255.255.0.0"

    findings = check_wrong_subnet_mask(ctx(state))

    assert [f for f in findings if "disagree" in f.message] == []


def test_r002_no_false_positive_on_clean_state():
    assert check_wrong_subnet_mask(ctx(clean_state())) == []


# ---------------------------------------------------------------------------------
# Integration through the engine
# ---------------------------------------------------------------------------------


def test_engine_reports_r001_and_r002_together():
    state = clean_state()
    state.host("PC-B").ip = "192.168.10.10"  # duplicate of PC-A -> R001
    state.host("PC-A").mask = "255.255.0.0"  # disagrees with gateway -> R002

    fired = rule_ids(run_rules(state, clean_flows()))

    assert "R001" in fired
    assert "R002" in fired


def test_findings_are_sorted_most_severe_first():
    state = clean_state()
    state.host("PC-B").ip = "192.168.10.10"  # R001, Critical
    state.host("PC-A").mask = "255.255.0.0"  # R002, High

    findings = run_rules(state, clean_flows())
    severities = [f.severity for f in findings]

    assert severities == sorted(severities, key=lambda s: {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}[s.value])
