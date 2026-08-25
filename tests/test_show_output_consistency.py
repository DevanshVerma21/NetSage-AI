"""Show-output consistency.

The rule engine reasons over ``lab_state``; the AI reasons over the Cisco ``show`` text.
If those two drift apart, the deterministic findings and the AI's cited evidence would
describe different networks — and the evidence verifier would be checking citations
against text that no longer matches reality.

These tests keep the two representations honest about the facts that matter.
"""

from __future__ import annotations

import pytest

from backend.app.services import case_repo


@pytest.fixture(scope="module")
def cases():
    case_repo.clear_cache()
    return case_repo.all_cases(use_cache=False)


def test_configured_ip_addresses_appear_in_the_show_text(cases):
    """Every IP in the structured state must be visible somewhere in the evidence.

    Otherwise the AI is asked to diagnose a fault it has no way to see.
    """
    for case in cases:
        corpus = case.all_output_text()
        for device in case.lab_state.devices:
            for iface in device.interfaces:
                if iface.ip:
                    assert iface.ip in corpus, (
                        f"{case.case_id}: {device.name} {iface.name} has IP {iface.ip} "
                        "in lab_state but it appears in no show output"
                    )


def test_host_addresses_and_gateways_appear_in_the_show_text(cases):
    for case in cases:
        corpus = case.all_output_text()
        for host in case.lab_state.hosts:
            if host.ip:
                assert host.ip in corpus, (
                    f"{case.case_id}: host {host.name} IP {host.ip} appears in no output"
                )


def test_device_names_in_show_outputs_exist_in_the_topology(cases):
    """A show output attributed to a device that is not in the topology is a data error."""
    for case in cases:
        known = {d.name.lower() for d in case.lab_state.devices}
        known |= {h.name.lower() for h in case.lab_state.hosts}
        for output in case.show_outputs:
            assert output.device.lower() in known, (
                f"{case.case_id}: show output attributed to unknown device "
                f"'{output.device}'"
            )


def test_show_output_commands_are_unique_per_device(cases):
    """Duplicate (device, command) pairs make evidence citations ambiguous."""
    for case in cases:
        seen: set[tuple[str, str]] = set()
        for output in case.show_outputs:
            key = (output.device.lower(), output.command.strip().lower())
            assert key not in seen, (
                f"{case.case_id}: duplicate show output for {output.device} "
                f"'{output.command}'"
            )
            seen.add(key)


def test_shutdown_interfaces_are_visible_as_down_in_the_evidence(cases):
    """If the state says an interface is down, a human must be able to see that."""
    for case in cases:
        corpus = case.all_output_text().lower()
        for device in case.lab_state.devices:
            for iface in device.interfaces:
                if not iface.is_down or not iface.ip:
                    continue
                assert "down" in corpus, (
                    f"{case.case_id}: {device.name} {iface.name} is down in lab_state "
                    "but no show output mentions a down state"
                )


def test_vlans_in_the_database_appear_in_vlan_output_when_captured(cases):
    """When a case captures 'show vlan brief', the VLANs it declares must be in it."""
    for case in cases:
        for device in case.lab_state.devices:
            output = case.show_output_for("show vlan brief", device.name)
            if output is None:
                continue
            for vlan in device.vlans:
                assert str(vlan.vlan_id) in output.output, (
                    f"{case.case_id}: VLAN {vlan.vlan_id} is in {device.name}'s database "
                    "but missing from its 'show vlan brief' output"
                )
