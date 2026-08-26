"""R007 access VLAN mismatch, R008 trunk/native VLAN mismatch, R009 overlapping subnets.

Each rule gets a positive test (the fault is detected) and a negative test (the healthy
topology from ``conftest.clean_state`` produces no finding, so the rule cannot be blamed
for a false positive on a working lab).
"""

from __future__ import annotations

from backend.app.models.enums import DeviceKind, LinkMode, SwitchportMode
from backend.app.models.lab_state import Device, Interface, Link, Vlan
from backend.app.rules.checks.subnets import check_overlapping_subnets
from backend.app.rules.checks.vlan_topology import (
    check_access_vlan_mismatch,
    check_trunk_vlan_mismatch,
)
from backend.app.rules.engine import RuleContext, run_rules
from tests.conftest import clean_flows, clean_state, rule_ids


def ctx(state, flows=None) -> RuleContext:
    return RuleContext(state=state, intended_flows=flows or [])


def _add_trunk(state, *, iface_allowed, iface_native, link_allowed, link_native):
    """Join SW1 to a second switch over a trunk with the given parameters."""
    state.device("SW1").interfaces.append(
        Interface(
            name="GigabitEthernet0/24",
            switchport_mode=SwitchportMode.TRUNK,
            allowed_vlans=list(iface_allowed),
            native_vlan=iface_native,
        )
    )
    state.devices.append(
        Device(
            name="SW2",
            kind=DeviceKind.SWITCH,
            ip_routing_enabled=False,
            vlans=[Vlan(vlan_id=1, name="default"), Vlan(vlan_id=10, name="SALES"),
                   Vlan(vlan_id=20, name="HR")],
            interfaces=[
                Interface(
                    name="GigabitEthernet0/24",
                    switchport_mode=SwitchportMode.TRUNK,
                    allowed_vlans=list(link_allowed),
                    native_vlan=link_native,
                )
            ],
        )
    )
    state.links.append(
        Link(
            a_device="SW1",
            a_interface="GigabitEthernet0/24",
            b_device="SW2",
            b_interface="GigabitEthernet0/24",
            mode=LinkMode.TRUNK,
            allowed_vlans=list(link_allowed),
            native_vlan=link_native,
        )
    )
    return state


# ---------------------------------------------------------------------------------
# R007 — access VLAN mismatch
# ---------------------------------------------------------------------------------


def test_r007_detects_an_access_port_in_the_wrong_vlan():
    state = clean_state()
    state.device("SW1").interface("GigabitEthernet0/1").vlan = 20  # segment is VLAN 10

    findings = check_access_vlan_mismatch(ctx(state))

    assert [f.rule_id for f in findings] == ["R007"]
    assert "access port in VLAN 20" in findings[0].message
    assert "VLAN 10" in findings[0].message


def test_r007_detects_a_host_cabled_into_the_wrong_vlan_segment():
    state = clean_state()
    state.host("PC-A").vlan = 20  # cabled to the VLAN 10 segment

    findings = check_access_vlan_mismatch(ctx(state))

    messages = [f.message for f in findings if "Host PC-A" in f.message]
    assert len(messages) == 1
    assert "member of VLAN 20" in messages[0]


def test_r007_does_not_fire_on_a_consistent_topology():
    assert check_access_vlan_mismatch(ctx(clean_state())) == []
    assert "R007" not in rule_ids(run_rules(clean_state(), clean_flows()))


# ---------------------------------------------------------------------------------
# R008 — trunk and native VLAN mismatch
# ---------------------------------------------------------------------------------


def test_r008_detects_a_vlan_pruned_from_a_trunk_that_must_carry_it():
    state = _add_trunk(
        clean_state(),
        iface_allowed=[10],  # VLAN 20 is pruned on SW1's end
        iface_native=1,
        link_allowed=[10, 20],
        link_native=1,
    )

    findings = check_trunk_vlan_mismatch(ctx(state))

    assert [f.rule_id for f in findings] == ["R008"]
    assert "does not carry VLAN 20" in findings[0].message


def test_r008_detects_a_native_vlan_disagreement():
    state = _add_trunk(
        clean_state(),
        iface_allowed=[10, 20],
        iface_native=99,  # the segment says native VLAN 1
        link_allowed=[10, 20],
        link_native=1,
    )

    findings = check_trunk_vlan_mismatch(ctx(state))

    assert [f.rule_id for f in findings] == ["R008"]
    assert "native VLAN 99" in findings[0].message


def test_r008_does_not_fire_on_a_matching_trunk():
    state = _add_trunk(
        clean_state(),
        iface_allowed=[10, 20],
        iface_native=1,
        link_allowed=[10, 20],
        link_native=1,
    )

    assert check_trunk_vlan_mismatch(ctx(state)) == []
    assert "R008" not in rule_ids(run_rules(clean_state(), clean_flows()))


# ---------------------------------------------------------------------------------
# R009 — overlapping subnets
# ---------------------------------------------------------------------------------


def test_r009_detects_a_mask_typo_that_swallows_another_subnet():
    state = clean_state()
    state.device("SW1").interface("Vlan10").mask = "255.255.0.0"  # 192.168.0.0/16

    findings = check_overlapping_subnets(ctx(state))

    assert [f.rule_id for f in findings] == ["R009"]
    assert "overlap" in findings[0].message


def test_r009_ignores_a_point_to_point_link_sharing_one_network():
    """Two directly connected interfaces in the same /30 are correct, not a fault."""
    state = clean_state()
    state.device("SW1").interfaces.append(
        Interface(name="GigabitEthernet0/23", ip="10.0.0.1", mask="255.255.255.252")
    )
    state.devices.append(
        Device(
            name="R1",
            kind=DeviceKind.ROUTER,
            interfaces=[
                Interface(name="GigabitEthernet0/0", ip="10.0.0.2", mask="255.255.255.252")
            ],
        )
    )
    state.links.append(
        Link(
            a_device="SW1",
            a_interface="GigabitEthernet0/23",
            b_device="R1",
            b_interface="GigabitEthernet0/0",
            mode=LinkMode.ROUTED,
        )
    )

    assert check_overlapping_subnets(ctx(state)) == []


def test_r009_does_not_fire_on_distinct_subnets():
    assert check_overlapping_subnets(ctx(clean_state())) == []
    assert "R009" not in rule_ids(run_rules(clean_state(), clean_flows()))
