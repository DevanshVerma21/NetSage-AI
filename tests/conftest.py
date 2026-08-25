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


# --- Phase 3: API and record-store fixtures ------------------------------------------------


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    """Point the record store at a temporary directory.

    Every API test writes diagnoses, reviews and fix runs. Without this they would append to
    the repository's real ``data/*.json`` files, so a test run would leave the working tree
    dirty and tests would see each other's records. The case dataset is still read from the
    real ``data/cases.json`` — that file is only ever read.
    """
    from backend.app.services import record_store

    monkeypatch.setattr(record_store, "records_dir", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def client(isolated_store):
    """A TestClient over the real app, with storage isolated to a temp directory."""
    from fastapi.testclient import TestClient

    from backend.app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def diagnosed(client):
    """One persisted diagnosis for CASE-001, produced through the mock provider.

    Returns the parsed diagnosis record body. Uses the API rather than the service directly
    so the fixture exercises the same path the demo flow does.
    """
    response = client.post("/api/diagnose", json={"case_id": "CASE-001", "provider": "mock"})
    assert response.status_code == 201, response.text
    return response.json()
