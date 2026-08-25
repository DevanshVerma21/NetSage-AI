"""Phase 3 — the Fix Simulator, tested directly rather than through HTTP.

Three properties matter more than any individual mutation:

1. the caller's :class:`LabState` is never touched — the simulator works on a deep copy
2. a mutation it cannot perform is *recorded as skipped*, never silently dropped and never
   raised out of the run, so the stored fix run says exactly what did and did not happen
3. verification is the rule engine re-run on the copy, so a fix that breaks something else
   cannot come back ``verified``

There is no device, no command, and no I/O anywhere in this path.
"""

from __future__ import annotations

import pytest

from backend.app.models.enums import AdminState, OperState
from backend.app.rules.engine import run_rules
from backend.app.services import fix_simulator
from backend.app.services.fix_simulator import MutationError, apply_mutations, settle
from tests.conftest import clean_flows, clean_state, rule_ids


def _shutdown(state, device: str, interface: str) -> None:
    iface = state.device(device).interface(interface)
    iface.admin_state = AdminState.SHUTDOWN
    iface.oper_state = OperState.DOWN


def _drop_vlan(state, device: str, vlan_id: int) -> None:
    dev = state.device(device)
    dev.vlans = [vlan for vlan in dev.vlans if vlan.vlan_id != vlan_id]


# --- the copy guarantee -------------------------------------------------------------------


def test_the_original_state_is_never_mutated(state, flows):
    _drop_vlan(state, "SW1", 20)
    before = state.model_dump(mode="json")

    outcome = apply_mutations(
        state,
        [{"type": "add_vlan", "device": "SW1", "vlan_id": 20, "name": "HR"}],
        intended_flows=flows,
    )

    assert state.model_dump(mode="json") == before, "the caller's state must be untouched"
    assert outcome.state_after is not None
    assert outcome.state_after.device("SW1").has_vlan(20)
    assert outcome.state_after is not state


def test_an_empty_mutation_list_changes_nothing(state, flows):
    outcome = apply_mutations(state, [], intended_flows=flows)
    assert outcome.mutations == []
    assert outcome.findings_before == [] and outcome.findings_after == []
    assert outcome.verification_result == "verified"


# --- the individual mutations -------------------------------------------------------------


def test_add_vlan_is_idempotent(state):
    detail = fix_simulator.add_vlan(state, "SW1", 10)
    assert "already present" in detail
    assert len([v for v in state.device("SW1").vlans if v.vlan_id == 10]) == 1


def test_add_vlan_creates_and_sorts(state):
    fix_simulator.add_vlan(state, "SW1", 30, "VLAN30")
    vlans = state.device("SW1").vlans
    assert [vlan.vlan_id for vlan in vlans] == sorted(vlan.vlan_id for vlan in vlans)
    assert state.device("SW1").has_vlan(30)


def test_set_interface_admin_state(state):
    detail = fix_simulator.set_interface_admin_state(state, "SW1", "GigabitEthernet0/1", "up")
    assert "admin state to up" in detail
    assert state.device("SW1").interface("GigabitEthernet0/1").admin_state == AdminState.UP


def test_set_host_gateway_and_mask(state):
    assert "192.168.10.1 -> 192.168.10.254" in fix_simulator.set_host_gateway(
        state, "PC-A", "192.168.10.254"
    )
    assert state.host("PC-A").gateway == "192.168.10.254"
    fix_simulator.set_host_mask(state, "PC-A", "255.255.255.128")
    assert state.host("PC-A").mask == "255.255.255.128"


def test_enable_ip_routing(state):
    state.device("SW1").ip_routing_enabled = False
    fix_simulator.enable_ip_routing(state, "SW1")
    assert state.device("SW1").ip_routing_enabled is True


def test_a_mutation_naming_something_absent_raises(state):
    with pytest.raises(MutationError, match="no device named"):
        fix_simulator.add_vlan(state, "SW9", 30)
    with pytest.raises(MutationError, match="no host named"):
        fix_simulator.set_host_gateway(state, "PC-Z", "192.168.10.1")
    with pytest.raises(MutationError, match="no interface"):
        fix_simulator.set_interface_admin_state(state, "SW1", "Gi9/9", "up")


def test_add_static_route_refuses_to_invent_a_next_hop(state):
    """The simulator will not guess a next hop the topology does not determine."""
    with pytest.raises(MutationError, match="A human must supply it"):
        fix_simulator.add_static_route(state, "SW1", "10.0.0.0", "255.255.255.0")

    detail = fix_simulator.add_static_route(
        state, "SW1", "10.0.0.0", "255.255.255.0", next_hop="192.168.10.2"
    )
    assert "via 192.168.10.2" in detail
    assert state.device("SW1").routes[-1].prefix == "10.0.0.0"


# --- settle -------------------------------------------------------------------------------


def test_settle_brings_an_svi_up_only_once_its_vlan_exists(state):
    _drop_vlan(state, "SW1", 20)
    settle(state)
    assert state.device("SW1").interface("Vlan20").oper_state == OperState.DOWN

    fix_simulator.add_vlan(state, "SW1", 20, "HR")
    settle(state)
    assert state.device("SW1").interface("Vlan20").oper_state == OperState.UP


def test_settle_keeps_a_shutdown_svi_down(state):
    state.device("SW1").interface("Vlan10").admin_state = AdminState.SHUTDOWN
    settle(state)
    assert state.device("SW1").interface("Vlan10").oper_state == OperState.DOWN


def test_settle_does_not_touch_physical_interfaces(state):
    """Whether a cable is plugged in is not something a config change can decide."""
    _shutdown(state, "SW1", "GigabitEthernet0/1")
    state.device("SW1").interface("GigabitEthernet0/1").admin_state = AdminState.UP
    settle(state)
    assert state.device("SW1").interface("GigabitEthernet0/1").oper_state == OperState.DOWN


# --- skips are recorded, never silent ----------------------------------------------------


def test_an_unsupported_mutation_type_is_recorded_as_skipped(state, flows):
    outcome = apply_mutations(
        state, [{"type": "reboot_device", "device": "SW1", "_rule_id": "R999"}], flows
    )
    assert len(outcome.mutations) == 1
    skipped = outcome.mutations[0]
    assert skipped.applied is False
    assert "not a mutation this simulator supports" in skipped.skipped_reason
    assert "A human must apply this change" in skipped.skipped_reason


def test_a_failing_mutation_is_recorded_rather_than_raised(state, flows):
    outcome = apply_mutations(
        state, [{"type": "add_vlan", "device": "SW-NOPE", "vlan_id": 30}], flows
    )
    assert outcome.mutations[0].applied is False
    assert "MutationError" in outcome.mutations[0].skipped_reason


def test_an_already_resolved_finding_is_skipped_with_a_reason(state, flows):
    """Fix minimisation: the second mutation for a rule that no longer fires is dropped."""
    _drop_vlan(state, "SW1", 20)
    before = rule_ids(run_rules(state, flows))
    assert before, "the fault must actually fire something first"
    target = before[0]

    outcome = apply_mutations(
        state,
        [
            {"type": "add_vlan", "device": "SW1", "vlan_id": 20, "name": "HR", "_rule_id": target},
            {
                "type": "add_static_route",
                "device": "SW1",
                "prefix": "192.168.20.0",
                "mask": "255.255.255.0",
                "_rule_id": target,
            },
        ],
        flows,
    )
    kinds = {mutation.type: mutation for mutation in outcome.mutations}
    assert kinds["add_vlan"].applied is True
    assert kinds["add_static_route"].applied is False
    assert "already resolved by an earlier step" in kinds["add_static_route"].skipped_reason


def test_mutations_are_applied_in_dependency_order(state, flows):
    """A VLAN is created before the SVI depending on it is brought up."""
    _drop_vlan(state, "SW1", 20)
    _shutdown(state, "SW1", "Vlan20")

    outcome = apply_mutations(
        state,
        [
            {"type": "set_interface_admin_state", "device": "SW1", "interface": "Vlan20"},
            {"type": "add_vlan", "device": "SW1", "vlan_id": 20, "name": "HR"},
        ],
        flows,
    )
    order = [mutation.type for mutation in outcome.mutations]
    assert order.index("add_vlan") < order.index("set_interface_admin_state")
    assert outcome.state_after.device("SW1").interface("Vlan20").oper_state == OperState.UP


# --- verification -------------------------------------------------------------------------


def test_a_clean_fix_verifies(state, flows):
    _drop_vlan(state, "SW1", 20)
    outcome = apply_mutations(
        state, [{"type": "add_vlan", "device": "SW1", "vlan_id": 20, "name": "HR"}], flows
    )
    assert outcome.findings_before
    assert outcome.findings_after == []
    assert outcome.resolved_rule_ids == outcome.before_ids
    assert outcome.new_rule_ids == []
    assert outcome.remaining_rule_ids == []
    assert outcome.verification_result == "verified"
    assert "resolved" in outcome.summary()


def test_a_fix_that_resolves_nothing_is_failed(state, flows):
    _drop_vlan(state, "SW1", 20)
    outcome = apply_mutations(
        state, [{"type": "enable_ip_routing", "device": "SW1"}], flows
    )
    assert outcome.resolved_rule_ids == []
    assert outcome.remaining_rule_ids == outcome.before_ids
    assert outcome.verification_result == "failed"


def test_a_fix_that_introduces_a_new_finding_is_never_verified(state, flows):
    """A remedy that breaks something else has not worked, whatever else it resolved."""
    outcome = apply_mutations(
        state, [{"type": "set_host_gateway", "host": "PC-A", "gateway": "10.99.99.1"}], flows
    )
    assert outcome.new_rule_ids, "a wrong gateway must fire a rule"
    assert outcome.verification_result == "failed"
    assert "NEWLY INTRODUCED" in outcome.summary()


def test_a_partial_fix_is_reported_as_partial(state, flows):
    _drop_vlan(state, "SW1", 20)
    _shutdown(state, "SW1", "GigabitEthernet0/1")
    before = rule_ids(run_rules(state, flows))
    assert len(before) >= 2, "two independent faults are needed for a partial fix"

    outcome = apply_mutations(
        state, [{"type": "add_vlan", "device": "SW1", "vlan_id": 20, "name": "HR"}], flows
    )
    assert outcome.resolved_rule_ids and outcome.remaining_rule_ids
    assert outcome.verification_result == "partial"
    assert "still firing" in outcome.summary()


def test_verification_reruns_the_same_engine(state, flows):
    """``findings_after`` must equal an independent run over the mutated copy."""
    _drop_vlan(state, "SW1", 20)
    outcome = apply_mutations(
        state, [{"type": "add_vlan", "device": "SW1", "vlan_id": 20, "name": "HR"}], flows
    )
    independent = run_rules(outcome.state_after, flows)
    assert rule_ids(outcome.findings_after) == rule_ids(independent)


def test_the_simulator_module_has_no_device_access():
    """No SSH, Telnet, Netmiko or command execution anywhere in this module.

    Asserted against the module's *imports* rather than its text: the docstring names those
    libraries in order to promise their absence, so a substring scan would fail on the
    promise itself.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(fix_simulator))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    for forbidden in ("paramiko", "netmiko", "telnetlib", "subprocess", "socket", "requests", "os"):
        assert forbidden not in imported
    assert imported <= {"dataclasses", "typing", "backend", "__future__"}
