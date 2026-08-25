"""Mock provider tests.

The mock provider is what makes the whole AI layer testable offline, so it is held to the
same standards as a real one: schema-valid, deterministic, never claiming execution, and
actually derived from the evidence rather than canned.
"""

from __future__ import annotations

import pytest

from backend.app.ai.base import DiagnoseRequest
from backend.app.ai.evidence_verifier import verify_evidence
from backend.app.ai.mock_provider import MockProvider
from backend.app.models.diagnosis import AIDiagnosis
from backend.app.rules.engine import run_rules
from backend.app.services import case_repo


@pytest.fixture(scope="module")
def case():
    case_repo.clear_cache()
    found = case_repo.get_case("CASE-001", use_cache=False)
    assert found is not None, "CASE-001 must exist for the Phase 2 vertical slice"
    return found


@pytest.fixture(scope="module")
def request_for_case(case):
    findings = run_rules(case.lab_state, case.intended_flows)
    return DiagnoseRequest.from_case(case, findings)


@pytest.fixture(scope="module")
def result(request_for_case):
    return MockProvider().diagnose(request_for_case)


# --- A. determinism ------------------------------------------------------------------


def test_mock_provider_is_deterministic(request_for_case):
    """Repeated calls must produce byte-identical diagnoses."""
    provider = MockProvider()
    first = provider.diagnose(request_for_case).diagnosis.model_dump()
    second = provider.diagnose(request_for_case).diagnosis.model_dump()
    third = MockProvider().diagnose(request_for_case).diagnosis.model_dump()

    assert first == second
    assert first == third


# --- B. schema validity --------------------------------------------------------------


def test_mock_output_is_a_valid_aidiagnosis(result):
    assert isinstance(result.diagnosis, AIDiagnosis)
    # Round-tripping through JSON re-runs every validator, including the model_validators.
    revalidated = AIDiagnosis.model_validate_json(result.diagnosis.model_dump_json())
    assert revalidated == result.diagnosis


def test_mock_confidence_score_sits_inside_its_band(result):
    assert result.diagnosis.confidence_score_matches_band


# --- P. no key required --------------------------------------------------------------


def test_mock_provider_needs_no_credentials(monkeypatch):
    """Even with every credential removed from the environment, mock works."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert MockProvider().is_available() is True


# --- labelling and honesty -----------------------------------------------------------


def test_mock_is_clearly_labelled_as_mock(result):
    assert result.provider == "mock"
    assert "mock" in result.diagnosis.notes_for_reviewer.lower()


def test_mock_reports_no_token_usage(result):
    """No tokens are consumed, so reporting a count would be fabrication."""
    assert result.token_usage is None


def test_mock_never_claims_a_fix_was_applied(result):
    """Scan every free-text field for perfect-tense execution claims."""
    forbidden = [
        "has been applied",
        "have been applied",
        "i applied",
        "we applied",
        "was applied",
        "has been fixed",
        "is now fixed",
        "已",  # guard against non-English creeping in via a future provider
        "successfully applied",
        "i have created",
        "has been created",
        "verified successfully",
    ]
    blob = result.diagnosis.model_dump_json().lower()
    for phrase in forbidden:
        assert phrase not in blob, f"mock output contains an execution claim: {phrase!r}"


def test_mock_fix_steps_are_imperative_recommendations(result):
    """Every step should read as an instruction, not a report."""
    for step in result.diagnosis.fix_steps:
        assert step.cli_commands
        assert step.rationale
        for command in step.cli_commands:
            assert command.strip()


# --- O. CASE-001 produces a meaningful diagnosis --------------------------------------


def test_case_001_diagnosis_identifies_the_real_root_cause(result):
    """CASE-001's ground truth is a VLAN that was never created. The mock must land on
    that, not on one of its downstream consequences."""
    diagnosis = result.diagnosis

    assert diagnosis.insufficient_evidence is False
    assert diagnosis.category == "VLAN"
    assert diagnosis.osi_layer == "L2"

    lowered = diagnosis.root_cause.lower()
    assert "vlan 30" in lowered
    assert "never created" in lowered or "does not exist" in lowered


def test_case_001_citations_come_from_multiple_commands(result):
    """Corroboration means several sources, not one output quoted three times."""
    commands = {item.source_command for item in result.diagnosis.evidence}
    assert len(result.diagnosis.evidence) >= 2
    assert len(commands) >= 2, f"all citations came from one command: {commands}"


def test_case_001_citations_all_verify_against_the_supplied_output(
    result, request_for_case
):
    """The offline happy path must genuinely pass the verifier, not bypass it."""
    verification = verify_evidence(
        result.diagnosis.evidence,
        request_for_case.evidence_corpus(),
        insufficient_evidence=result.diagnosis.insufficient_evidence,
    )
    assert verification.status == "passed", verification.details
    assert verification.failed_count == 0


def test_case_001_citations_are_diagnostic_not_command_echoes(result):
    """Guards against the verifier being satisfied by trivially-quoted noise."""
    echoes = ("pinging ", "ping statistics", "packets: sent")
    for item in result.diagnosis.evidence:
        lowered = item.excerpt.lower()
        assert not lowered.startswith("pc-hr>"), f"cited a prompt echo: {item.excerpt!r}"
        for echo in echoes:
            assert echo not in lowered, f"cited banner text: {item.excerpt!r}"


def test_case_001_fix_steps_are_in_a_runnable_order(result):
    """The VLAN must be created before the SVI is brought up, or the fix fails."""
    steps = result.diagnosis.fix_steps
    assert len(steps) >= 2

    flattened = [" ".join(step.cli_commands).lower() for step in steps]
    vlan_index = next(i for i, text in enumerate(flattened) if "vlan 30" in text)
    noshut_index = next(i for i, text in enumerate(flattened) if "no shutdown" in text)

    assert vlan_index < noshut_index, (
        "'no shutdown' on the SVI is proposed before the VLAN exists, which would fail"
    )


def test_case_001_proposes_verification_for_every_rule_that_fired(
    result, request_for_case
):
    """A fix is not complete unless each deterministic finding has a way to be shown
    resolved."""
    steps = result.diagnosis.verification_steps
    assert steps

    for step in steps:
        assert step.command.strip()
        assert step.expected_result.strip()

    fired = {f.rule_id for f in request_for_case.rule_findings}
    covered = " ".join(step.expected_result for step in steps)
    missing = [rule_id for rule_id in sorted(fired) if rule_id not in covered]

    assert not missing, f"no verification step closes out: {missing}"


# --- behaviour with no findings -------------------------------------------------------


def test_mock_declines_when_there_are_no_rule_findings(case):
    """No deterministic findings means nothing to ground a cause in, so it must decline
    rather than invent one."""
    request = DiagnoseRequest(
        symptom=case.symptom,
        topology_note=case.topology_note,
        show_outputs=list(case.show_outputs),
        rule_findings=[],
        case_id=case.case_id,
    )

    diagnosis = MockProvider().diagnose(request).diagnosis

    assert diagnosis.insufficient_evidence is True
    assert diagnosis.confidence == "low"
    assert diagnosis.fix_steps == [], "no fix should be proposed without a grounded cause"
    assert diagnosis.next_command.strip()


def test_mock_handles_a_request_with_no_show_outputs():
    """Degenerate input must not crash the provider."""
    request = DiagnoseRequest(
        symptom="Nothing works.",
        topology_note="One switch, one PC.",
        show_outputs=[],
        rule_findings=[],
    )

    diagnosis = MockProvider().diagnose(request).diagnosis

    assert diagnosis.insufficient_evidence is True
    assert diagnosis.evidence == []
    assert diagnosis.next_command.strip()
