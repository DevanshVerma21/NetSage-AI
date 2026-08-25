"""Shared test fixtures.

``clean_state()`` returns a small, deliberately healthy topology that fires **zero**
rules. Every negative test ("this rule must not false-positive") asserts against it, and
every positive test starts from it and introduces exactly one fault. That keeps each test
honest about what it is actually proving.
"""

from __future__ import annotations

import pytest

from backend.app.models.enums import (
    AdminState,
    DeviceKind,
    FlowExpect,
    LinkMode,
    OperState,
    SwitchportMode,
)
from backend.app.models.lab_state import (
    Device,
    Host,
    IntendedFlow,
    Interface,
    LabState,
    Link,
    Vlan,
)


def clean_state() -> LabState:
    """A healthy two-VLAN inter-VLAN routing topology. Fires no rules.

    Built fresh on every call so a test that mutates it cannot leak into another.
    """
    sw1 = Device(
        name="SW1",
        kind=DeviceKind.MULTILAYER_SWITCH,
        ip_routing_enabled=True,
        vlans=[
            Vlan(vlan_id=1, name="default"),
            Vlan(vlan_id=10, name="SALES"),
            Vlan(vlan_id=20, name="HR"),
        ],
        interfaces=[
            Interface(
                name="GigabitEthernet0/1",
                switchport_mode=SwitchportMode.ACCESS,
                vlan=10,
                admin_state=AdminState.UP,
                oper_state=OperState.UP,
            ),
            Interface(
                name="GigabitEthernet0/2",
                switchport_mode=SwitchportMode.ACCESS,
                vlan=20,
                admin_state=AdminState.UP,
                oper_state=OperState.UP,
            ),
            Interface(
                name="Vlan10",
                ip="192.168.10.1",
                mask="255.255.255.0",
                is_svi=True,
                vlan=10,
            ),
            Interface(
                name="Vlan20",
                ip="192.168.20.1",
                mask="255.255.255.0",
                is_svi=True,
                vlan=20,
            ),
        ],
    )

    return LabState(
        devices=[sw1],
        hosts=[
            Host(
                name="PC-A",
                ip="192.168.10.10",
                mask="255.255.255.0",
                gateway="192.168.10.1",
                vlan=10,
                connected_device="SW1",
                connected_interface="GigabitEthernet0/1",
            ),
            Host(
                name="PC-B",
                ip="192.168.20.10",
                mask="255.255.255.0",
                gateway="192.168.20.1",
                vlan=20,
                connected_device="SW1",
                connected_interface="GigabitEthernet0/2",
            ),
        ],
        links=[
            Link(
                a_device="SW1",
                a_interface="GigabitEthernet0/1",
                b_device="PC-A",
                b_interface="FastEthernet0",
                mode=LinkMode.ACCESS,
                access_vlan=10,
            ),
            Link(
                a_device="SW1",
                a_interface="GigabitEthernet0/2",
                b_device="PC-B",
                b_interface="FastEthernet0",
                mode=LinkMode.ACCESS,
                access_vlan=20,
            ),
        ],
    )


def clean_flows() -> list[IntendedFlow]:
    """Intended traffic for the clean topology: the two PCs may talk to each other."""
    return [
        IntendedFlow(src="PC-A", dst="PC-B", proto="ip", expect=FlowExpect.PERMIT),
        IntendedFlow(src="PC-B", dst="PC-A", proto="ip", expect=FlowExpect.PERMIT),
    ]


@pytest.fixture
def state() -> LabState:
    return clean_state()


@pytest.fixture
def flows() -> list[IntendedFlow]:
    return clean_flows()


def rule_ids(findings) -> list[str]:
    """Sorted unique rule ids from a findings list — the usual assertion target."""
    return sorted({f.rule_id for f in findings})
