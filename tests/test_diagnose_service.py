"""Diagnosis service tests — the ten-step pipeline end to end, offline.

These assert the properties that the later phases will depend on, most importantly that no
code path in this service can produce a result that is already reviewed or already applied.
"""

from __future__ import annotations

import pytest

from backend.app.ai.base import DiagnoseRequest
from backend.app.ai.mock_provider import MockProvider
from backend.app.models.diagnosis import AIDiagnosis, Evidence
from backend.app.rules.engine import run_rules
from backend.app.services import case_repo
from backend.app.services.diagnose import AWAITING_REVIEW, diagnose_case, diagnose_request


@pytest.fixture(scope="module")
def case():
    case_repo.clear_cache()
    return case_repo.get_case("CASE-001", use_cache=False)


@pytest.fixture(scope="module")
def result(case):
    return diagnose_case(case, provider=MockProvider())


# --- the human gate -------------------------------------------------------------------


def test_every_diagnosis_starts_awaiting_human_review(result):
    assert result.status == AWAITING_REVIEW
    assert result.applied is False
    assert result.requires_human_review is True


def test_no_provider_can_produce_an_applied_result(case):
    """Even a provider that tries to claim completion cannot set applied/status."""

    class OverconfidentProvider:
        name = "overconfident"
        model = "test"

        def is_available(self) -> bool:
            return True

        def diagnose(self, request):
            from backend.app.ai.base import ProviderResult

            return ProviderResult(
                diagnosis=AIDiagnosis(
                    root_cause="I have already fixed this.",
                    confidence="high",
                    confidence_score=0.99,
                    osi_layer="L2",
                    category="VLAN",
                    evidence=[
                        Evidence(
                            source_command="show vlan brief",
                            excerpt="10   SALES",
                            why_it_matters="test",
                        )
                    ],
                    insufficient_evidence=False,
                    next_command="show vlan brief",
                    notes_for_reviewer="test",
                ),
                provider=self.name,
                model=self.model,
                latency_ms=1,
            )

    outcome = diagnose_case(case, provider=OverconfidentProvider())

    assert outcome.status == AWAITING_REVIEW
    assert outcome.applied is False


# --- provenance -----------------------------------------------------------------------


def test_result_records_the_prompt_identity(result):
    """A stored diagnosis must be traceable to the exact instruction text used."""
    assert result.prompt_name == "diagnose_prompt"
    assert result.prompt_version == "1.2.1"
    assert len(result.prompt_sha256) == 64


def test_result_records_provider_and_model(result):
    assert result.provider == "mock"
    assert result.model
    assert result.created_at


def test_result_carries_the_deterministic_findings(result):
    """The rule findings travel with the diagnosis so a reviewer sees both halves."""
    assert result.rule_findings
    assert {f.rule_id for f in result.rule_findings} == {"R004", "R005", "R006"}


# --- the verification stages ran ------------------------------------------------------


def test_evidence_verification_ran(result):
    assert result.evidence_integrity in {"passed", "partial", "failed"}
    assert result.evidence_verification.total_count == len(result.ai.evidence)


def test_reconciliation_ran(result):
    assert result.agreement in {"agree", "partial", "ai_only", "rules_only", "conflict"}


def test_confidence_capping_ran(result):
    assert result.model_confidence in {"low", "medium", "high"}
    assert result.effective_confidence in {"low", "medium", "high"}


def test_case_001_reaches_high_confidence_legitimately(result):
    """CASE-001 is a corroborated fault: multiple verified citations and rule agreement,
    so HIGH should survive capping. This is the offline happy path."""
    assert result.evidence_integrity == "passed"
    assert result.agreement == "agree"
    assert result.effective_confidence == "high"
    assert result.confidence.was_capped is False


# --- the failure path -----------------------------------------------------------------


def test_fabricated_evidence_caps_confidence_and_warns(case):
    """A provider that invents citations must be caught by the pipeline, not trusted."""

    class FabricatingProvider:
        name = "fabricating"
        model = "test"

        def is_available(self) -> bool:
            return True

        def diagnose(self, request):
            from backend.app.ai.base import ProviderResult

            return ProviderResult(
                diagnosis=AIDiagnosis(
                    root_cause="VLAN 40 is missing from the database.",
                    confidence="high",
                    confidence_score=0.95,
                    osi_layer="L2",
                    category="VLAN",
                    evidence=[
                        Evidence(
                            source_command="show vlan brief",
                            excerpt="40   DATABASE                         active    Gi0/9",
                            why_it_matters="Invented — this line does not exist.",
                        )
                    ],
                    insufficient_evidence=False,
                    next_command="show vlan brief",
                    notes_for_reviewer="test",
                ),
                provider=self.name,
                model=self.model,
                latency_ms=1,
            )

    outcome = diagnose_case(case, provider=FabricatingProvider())

    assert outcome.evidence_integrity == "failed"
    assert outcome.model_confidence == "high"
    assert outcome.effective_confidence == "low"
    assert any("EVIDENCE INTEGRITY FAILED" in w for w in outcome.warnings)
    # The diagnosis is preserved for the reviewer, not discarded.
    assert outcome.ai.root_cause


def test_failed_citations_remain_visible_to_the_reviewer(case):
    """The reviewer must be able to see exactly what was fabricated."""

    class FabricatingProvider:
        name = "fabricating"
        model = "test"

        def is_available(self) -> bool:
            return True

        def diagnose(self, request):
            from backend.app.ai.base import ProviderResult

            return ProviderResult(
                diagnosis=AIDiagnosis(
                    root_cause="Invented cause.",
                    confidence="high",
                    confidence_score=0.9,
                    osi_layer="L2",
                    category="VLAN",
                    evidence=[
                        Evidence(
                            source_command="show vlan brief",
                            excerpt="99   GHOST_VLAN",
                            why_it_matters="fabricated",
                        )
                    ],
                    insufficient_evidence=False,
                    next_command="show vlan brief",
                    notes_for_reviewer="test",
                ),
                provider=self.name,
                model=self.model,
                latency_ms=1,
            )

    outcome = diagnose_case(case, provider=FabricatingProvider())

    assert outcome.evidence_verification.failed_items
    assert outcome.evidence_verification.failed_items[0].excerpt == "99   GHOST_VLAN"


# --- request construction -------------------------------------------------------------


def test_request_does_not_leak_ground_truth(case):
    """Putting expected_fault into the prompt would make every AI evaluation worthless."""
    findings = run_rules(case.lab_state, case.intended_flows)
    rendered = DiagnoseRequest.from_case(case, findings).render()

    assert case.expected_fault not in rendered
    for keyword_phrase in case.expected_fix_steps:
        assert keyword_phrase not in rendered
    assert "expected_rule_ids" not in rendered
    assert "expected_fault" not in rendered


def test_request_contains_the_five_required_sections(case):
    findings = run_rules(case.lab_state, case.intended_flows)
    rendered = DiagnoseRequest.from_case(case, findings).render()

    for section in (
        "USER SYMPTOM",
        "TOPOLOGY",
        "OBSERVED EVIDENCE",
        "RULE FINDINGS",
        "TASK",
    ):
        assert section in rendered


def test_request_renders_no_python_object_repr(case):
    """The model must see clean text, never a serialised Python object."""
    findings = run_rules(case.lab_state, case.intended_flows)
    rendered = DiagnoseRequest.from_case(case, findings).render()

    assert "object at 0x" not in rendered
    assert "Finding(" not in rendered
    assert "ShowOutput(" not in rendered
    assert "<backend." not in rendered


def test_request_includes_the_deterministic_findings_as_context(case):
    findings = run_rules(case.lab_state, case.intended_flows)
    rendered = DiagnoseRequest.from_case(case, findings).render()

    assert "[R005]" in rendered
    assert "[R004]" in rendered


def test_request_states_when_no_rules_fired():
    request = DiagnoseRequest(
        symptom="test", topology_note="test", show_outputs=[], rule_findings=[]
    )
    rendered = request.render()

    assert "(none" in rendered
    assert "does not prove the network is healthy" in rendered


def test_evidence_corpus_maps_commands_to_output(case):
    findings = run_rules(case.lab_state, case.intended_flows)
    corpus = DiagnoseRequest.from_case(case, findings).evidence_corpus()

    assert "show vlan brief" in corpus
    assert "SERVERS" not in corpus["show vlan brief"]  # VLAN 30 is genuinely absent
    assert "SALES" in corpus["show vlan brief"]


# --- determinism of the whole pipeline ------------------------------------------------


def test_pipeline_is_deterministic_with_the_mock_provider(case):
    first = diagnose_case(case, provider=MockProvider())
    second = diagnose_case(case, provider=MockProvider())

    assert first.ai.model_dump() == second.ai.model_dump()
    assert first.evidence_integrity == second.evidence_integrity
    assert first.agreement == second.agreement
    assert first.effective_confidence == second.effective_confidence


def test_summary_lines_are_renderable(result):
    lines = result.summary_lines()
    assert any("effective conf." in line for line in lines)
    assert any("awaiting_human_review" in line for line in lines)


def test_diagnose_request_entry_point_works(case):
    """The ad-hoc path (no stored case) must work the same way."""
    findings = run_rules(case.lab_state, case.intended_flows)
    request = DiagnoseRequest(
        symptom=case.symptom,
        topology_note=case.topology_note,
        show_outputs=list(case.show_outputs),
        rule_findings=findings,
    )

    outcome = diagnose_request(request, provider=MockProvider())

    assert outcome.case_id is None
    assert outcome.status == AWAITING_REVIEW
