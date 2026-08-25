"""Dataset integrity tests.

Phase 1 asserts the *shape* of the dataset and the invariants that must hold at every
size. The full 40-case count and 9-category coverage assertions arrive in Phase 5; the
placeholders below are written so they tighten automatically as cases are added.
"""

from __future__ import annotations

import pytest

from backend.app.models.enums import ConceptTag, SourceLabel
from backend.app.services import case_repo

# The reviewer-approved target distribution (amendment 2). Enforced in Phase 5.
TARGET_DISTRIBUTION = {
    ConceptTag.VLAN: 5,
    ConceptTag.GATEWAY: 5,
    ConceptTag.DHCP: 5,
    ConceptTag.DNS: 4,
    ConceptTag.ROUTING: 5,
    ConceptTag.ACL: 4,
    ConceptTag.NAT: 4,
    ConceptTag.WIRELESS: 4,
    ConceptTag.INTERFACE_CONFIG: 4,
}
TARGET_TOTAL = 40


@pytest.fixture(scope="module")
def cases():
    case_repo.clear_cache()
    return case_repo.all_cases(use_cache=False)


def test_dataset_loads_and_validates(cases):
    """A malformed dataset must fail loudly here, not silently at runtime."""
    assert len(cases) >= 1


def test_case_ids_are_unique(cases):
    ids = [case.case_id for case in cases]
    assert len(ids) == len(set(ids)), "duplicate case_id in the dataset"


def test_case_ids_follow_the_naming_convention(cases):
    for case in cases:
        assert case.case_id.startswith("CASE-"), case.case_id
        suffix = case.case_id.removeprefix("CASE-")
        assert suffix.isdigit() and len(suffix) == 3, case.case_id


def test_every_mandatory_evidence_field_is_populated(cases):
    """The six 'Evidence per case' fields from the company document, plus severity."""
    for case in cases:
        assert case.symptom.strip(), f"{case.case_id}: empty symptom"
        assert case.topology_note.strip(), f"{case.case_id}: empty topology_note"
        assert case.show_outputs, f"{case.case_id}: no show outputs"
        assert case.expected_fault.strip(), f"{case.case_id}: empty expected_fault"
        assert case.osi_layer is not None, f"{case.case_id}: no osi_layer"
        assert case.concept_tag is not None, f"{case.case_id}: no concept_tag"
        assert case.severity is not None, f"{case.case_id}: no severity"


def test_show_outputs_are_non_empty_and_named(cases):
    for case in cases:
        for output in case.show_outputs:
            assert output.device.strip(), f"{case.case_id}: show output with no device"
            assert output.command.strip(), f"{case.case_id}: show output with no command"
            assert output.output.strip(), (
                f"{case.case_id}: '{output.command}' has empty output text"
            )


def test_every_case_is_labelled_as_simulated(cases):
    """Development rule 5: simulated cases must be labelled as such. The prototype never
    claims a real Packet Tracer or hardware capture."""
    for case in cases:
        assert case.source_label == SourceLabel.SIMULATED_LAB, case.case_id


def test_every_case_declares_expected_rule_ids(cases):
    """Without this the golden test cannot validate the engine against the dataset."""
    for case in cases:
        assert case.expected_rule_ids, f"{case.case_id}: no expected_rule_ids declared"


def test_every_case_has_a_lab_state_with_devices_and_hosts(cases):
    for case in cases:
        assert case.lab_state.devices, f"{case.case_id}: lab_state has no devices"
        assert case.lab_state.hosts, f"{case.case_id}: lab_state has no hosts"


def test_intended_flow_endpoints_exist_in_the_lab_state(cases):
    """A flow naming a host that does not exist would silently disable R006."""
    for case in cases:
        host_names = {h.name.lower() for h in case.lab_state.hosts}
        for flow in case.intended_flows:
            assert flow.src.lower() in host_names, (
                f"{case.case_id}: intended flow src '{flow.src}' is not a host"
            )
            assert flow.dst.lower() in host_names, (
                f"{case.case_id}: intended flow dst '{flow.dst}' is not a host"
            )


def test_expected_root_cause_keywords_are_present(cases):
    for case in cases:
        assert case.expected_root_cause_keywords, (
            f"{case.case_id}: no keywords for scoring AI output against ground truth"
        )


def test_expected_fix_steps_are_present(cases):
    for case in cases:
        assert case.expected_fix_steps, f"{case.case_id}: no reference fix steps"


def test_concept_tags_are_within_the_approved_taxonomy(cases):
    for case in cases:
        assert case.concept_tag in TARGET_DISTRIBUTION, (
            f"{case.case_id}: {case.concept_tag} is outside the approved distribution"
        )


# ---------------------------------------------------------------------------------
# Phase 5 gates — deliberately skipped until the dataset is expanded to 40 cases.
# ---------------------------------------------------------------------------------


def test_dataset_reaches_forty_cases(cases):
    if len(cases) < TARGET_TOTAL:
        pytest.skip(
            f"Phase 5 gate: {len(cases)}/{TARGET_TOTAL} cases authored so far "
            "(Phase 1 builds the vertical slice on one case first)"
        )
    assert len(cases) == TARGET_TOTAL


def test_distribution_matches_the_approved_plan(cases):
    if len(cases) < TARGET_TOTAL:
        pytest.skip(f"Phase 5 gate: dataset is at {len(cases)}/{TARGET_TOTAL} cases")
    actual = case_repo.coverage_by_concept(use_cache=False)
    expected = {tag.value: count for tag, count in TARGET_DISTRIBUTION.items()}
    assert actual == expected
