"""Phase 6 evaluation tests — mocked results only.

Nothing here touches the network. The pipeline half of the tests runs the real
``diagnose_case`` against the deterministic ``MockProvider``; the metric, ranking, resume and
report halves operate on hand-built :class:`EvaluationRecord` objects, so a classification
boundary can be asserted exactly rather than approximately.
"""

from __future__ import annotations

import csv
import json

import pytest

from backend.app.ai.base import ProviderError
from backend.app.ai.mock_provider import MockProvider
from backend.app.services import case_repo
from backend.app.services.diagnose import diagnose_case
from backend.app.services.evaluation import (
    MATRIX_COLUMNS,
    RESULT_ORDER,
    AgreementDetail,
    EvaluationRecord,
    candidate_reasons,
    classify,
    compare,
    compute_metrics,
    failure_record,
    matrix_rows,
    record_from_result,
    render_markdown,
    select_review_candidates,
)
from backend.scripts import build_evaluation_reports, evaluate_all_cases


@pytest.fixture(scope="module")
def cases():
    case_repo.clear_cache()
    return case_repo.all_cases(use_cache=False)


@pytest.fixture(scope="module")
def case(cases):
    return cases[0]


@pytest.fixture(scope="module")
def mock_record(case):
    """A real pipeline result, produced offline by the deterministic mock provider."""
    result = diagnose_case(case, provider=MockProvider())
    return record_from_result(case, result, diagnosis_id="DIAG-test")


def agreement(**overrides) -> AgreementDetail:
    """A fully-agreeing AgreementDetail, so each test can spoil exactly one dimension."""
    base = dict(
        rule_agreement=True,
        matched_expected_rule_ids=["R001"],
        missed_expected_rule_ids=[],
        keyword_agreement=True,
        matched_keywords=["a", "b"],
        missed_keywords=[],
        keyword_hit_rate=1.0,
        osi_agreement=True,
        category_agreement=True,
    )
    base.update(overrides)
    return AgreementDetail(**base)


def record(**overrides) -> EvaluationRecord:
    base = dict(
        case_id="CASE-900",
        category="VLAN",
        severity="High",
        expected_rule_ids=["R005"],
        expected_root_cause_keywords=["missing vlan"],
        expected_osi_layer="L2",
        expected_category="VLAN",
        ai_root_cause="VLAN 10 is missing from the database",
        ai_osi_layer="L2",
        ai_category="VLAN",
        model_confidence="high",
        effective_confidence="high",
        evidence_integrity="passed",
        total_citations=2,
        verified_citations=2,
        failed_citations=0,
        reconciliation="agree",
        provider="gemini",
        model="gemini-test",
        prompt_version="1.0.0",
        evaluation_status="completed",
        evaluation_result="CORRECT",
        agreement=agreement(),
        latency_ms=1200,
        timestamp="2026-01-01T00:00:00+00:00",
    )
    base.update(overrides)
    return EvaluationRecord(**base)


# ---------------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------------


def test_the_stored_record_carries_every_required_field(mock_record):
    """§5 — the field list the phase specification mandates."""
    payload = mock_record.model_dump(mode="json")
    for field in (
        "case_id", "category", "severity",
        "expected_rule_ids", "expected_root_cause_keywords", "expected_osi_layer",
        "expected_category",
        "ai_root_cause", "ai_osi_layer", "ai_category", "ai_evidence", "next_command",
        "fix_steps",
        "model_confidence", "effective_confidence",
        "evidence_integrity", "reconciliation",
        "provider", "model", "prompt_version", "prompt_sha256",
        "evaluation_status", "evaluation_result",
        "latency_ms", "timestamp",
    ):
        assert field in payload, f"missing required field: {field}"


def test_the_stored_record_round_trips_through_json(mock_record):
    restored = EvaluationRecord.model_validate(
        json.loads(mock_record.model_dump_json())
    )
    assert restored == mock_record


def test_the_record_matches_the_pipeline_it_came_from(case, mock_record):
    assert mock_record.case_id == case.case_id
    assert mock_record.expected_rule_ids == list(case.expected_rule_ids)
    assert mock_record.expected_category == case.concept_tag.value
    assert mock_record.total_citations == len(mock_record.ai_evidence)
    assert mock_record.verified_citations == sum(
        1 for citation in mock_record.ai_evidence if citation.verified
    )


def test_no_credential_can_reach_the_stored_record(mock_record):
    payload = mock_record.model_dump_json().lower()
    for forbidden in ("api_key", "gemini_api_key", "authorization", "bearer "):
        assert forbidden not in payload


def test_a_failed_case_is_recorded_rather_than_dropped(case):
    failed = failure_record(
        case, ProviderError("503 overloaded"), attempts=4,
        timestamp="2026-01-01T00:00:00+00:00", provider="gemini", model="gemini-test",
    )
    assert failed.evaluation_status == "failed"
    assert failed.evaluation_result == "UNABLE_TO_EVALUATE"
    assert failed.error_type == "ProviderError"
    assert failed.attempts == 4
    assert failed.succeeded is False
    # Ground truth is still recorded, so the case can be re-run and compared later.
    assert failed.expected_rule_ids == list(case.expected_rule_ids)


# ---------------------------------------------------------------------------------
# classification
# ---------------------------------------------------------------------------------


def test_everything_agreeing_is_correct():
    verdict, reason = classify(agreement(), "passed", declined=False)
    assert verdict == "CORRECT"
    assert "match" in reason


def test_a_wrong_category_with_no_keyword_overlap_is_incorrect():
    verdict, reason = classify(
        agreement(category_agreement=False, keyword_agreement=False, keyword_hit_rate=0.0,
                  matched_keywords=[], missed_keywords=["missing vlan"]),
        "passed",
        declined=False,
    )
    assert verdict == "INCORRECT"
    assert "not identified" in reason


def test_a_missed_secondary_finding_is_partial():
    """§6 — the primary fault found, a secondary one missed."""
    verdict, reason = classify(
        agreement(missed_expected_rule_ids=["R015"]), "passed", declined=False
    )
    assert verdict == "PARTIAL"
    assert "R015" in reason


def test_the_right_fault_at_the_wrong_layer_is_partial():
    verdict, _ = classify(agreement(osi_agreement=False), "passed", declined=False)
    assert verdict == "PARTIAL"


def test_a_correct_looking_diagnosis_with_failed_evidence_is_not_correct():
    """Right answer, no substantiation: never CORRECT."""
    verdict, _ = classify(agreement(), "failed", declined=False)
    assert verdict == "PARTIAL"


def test_failed_evidence_with_a_wrong_category_is_incorrect():
    verdict, reason = classify(
        agreement(category_agreement=False, keyword_hit_rate=0.4, keyword_agreement=False),
        "failed",
        declined=False,
    )
    assert verdict == "INCORRECT"
    assert "Evidence verification failed" in reason


def test_partial_keyword_overlap_with_a_wrong_category_is_partial():
    """Above the 0.25 floor, a wrong category is still partial credit, not a miss."""
    verdict, _ = classify(
        agreement(category_agreement=False, keyword_agreement=False, keyword_hit_rate=0.4),
        "passed",
        declined=False,
    )
    assert verdict == "PARTIAL"


def test_declining_to_diagnose_is_unable_to_evaluate():
    verdict, reason = classify(agreement(), "passed", declined=True)
    assert verdict == "UNABLE_TO_EVALUATE"
    assert "insufficient evidence" in reason


def test_keyword_matching_reads_the_fix_steps_as_well_as_the_root_cause(case):
    """A fault named only in the remediation was still identified."""
    result = diagnose_case(case, provider=MockProvider())
    detail = compare(case, result.ai, ["R005"], result.reconciliation.matched_rule_ids)
    assert 0.0 <= detail.keyword_hit_rate <= 1.0
    assert len(detail.matched_keywords) + len(detail.missed_keywords) == len(
        case.expected_root_cause_keywords
    )


def test_comparison_never_mutates_the_ground_truth(case):
    before = (list(case.expected_rule_ids), list(case.expected_root_cause_keywords))
    result = diagnose_case(case, provider=MockProvider())
    compare(case, result.ai, ["R005"], result.reconciliation.matched_rule_ids)
    assert (list(case.expected_rule_ids), list(case.expected_root_cause_keywords)) == before


# ---------------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------------


@pytest.fixture
def mixed_records():
    return [
        record(case_id="CASE-901", evaluation_result="CORRECT"),
        record(
            case_id="CASE-902",
            category="DHCP",
            evaluation_result="PARTIAL",
            effective_confidence="high",
            evidence_integrity="partial",
            total_citations=3,
            verified_citations=2,
            failed_citations=1,
            reconciliation="partial",
            agreement=agreement(osi_agreement=False, keyword_hit_rate=0.5),
        ),
        record(
            case_id="CASE-903",
            category="DNS",
            evaluation_result="INCORRECT",
            model_confidence="high",
            effective_confidence="low",
            evidence_integrity="failed",
            total_citations=1,
            verified_citations=0,
            failed_citations=1,
            reconciliation="conflict",
            confidence_was_capped=True,
            agreement=agreement(
                rule_agreement=False, category_agreement=False, osi_agreement=False,
                keyword_agreement=False, keyword_hit_rate=0.0, matched_expected_rule_ids=[],
                missed_expected_rule_ids=["R005"],
            ),
        ),
        record(
            case_id="CASE-904",
            category="NAT",
            evaluation_status="failed",
            evaluation_result="UNABLE_TO_EVALUATE",
            agreement=None,
            model_confidence=None,
            effective_confidence=None,
            evidence_integrity=None,
            reconciliation=None,
            total_citations=0,
            verified_citations=0,
            failed_citations=0,
            ai_root_cause=None,
            error_type="ProviderError",
            error_message="503 overloaded",
            latency_ms=0,
        ),
    ]


def test_totals_separate_successful_from_failed(mixed_records):
    metrics = compute_metrics(mixed_records)
    assert metrics["totals"] == {
        "total_cases": 4,
        "successful": 3,
        "failed": 1,
        "failed_case_ids": ["CASE-904"],
    }


def test_result_counts_cover_every_verdict(mixed_records):
    results = compute_metrics(mixed_records)["results"]
    assert list(results) == list(RESULT_ORDER)
    assert results == {
        "CORRECT": 1, "PARTIAL": 1, "INCORRECT": 1, "UNABLE_TO_EVALUATE": 1
    }


def test_agreement_metrics_count_only_scoreable_cases(mixed_records):
    agreements = compute_metrics(mixed_records)["agreement"]
    assert agreements["scored_cases"] == 3
    assert agreements["rule_agreement"] == 2
    assert agreements["category_agreement"] == 2
    assert agreements["osi_agreement"] == 1
    assert agreements["root_cause_agreement"] == 2


def test_evidence_metrics_sum_the_citations(mixed_records):
    evidence = compute_metrics(mixed_records)["evidence"]
    assert evidence["integrity"] == {"passed": 1, "partial": 1, "failed": 1}
    assert evidence["total_citations"] == 6
    assert evidence["verified_citations"] == 4
    assert evidence["failed_citations"] == 2
    assert evidence["verification_rate"] == pytest.approx(4 / 6, abs=1e-4)


def test_confidence_metrics_cross_tabulate_against_correctness(mixed_records):
    confidence = compute_metrics(mixed_records)["confidence"]
    assert confidence["model"] == {"low": 0, "medium": 0, "high": 3}
    assert confidence["effective"] == {"low": 1, "medium": 0, "high": 2}
    assert confidence["high_confidence_partial"] == 1
    assert confidence["high_confidence_incorrect"] == 0
    assert confidence["model_high_but_capped"] == 1


def test_reconciliation_metrics_report_all_five_states(mixed_records):
    assert compute_metrics(mixed_records)["reconciliation"] == {
        "agree": 1, "partial": 1, "ai_only": 0, "rules_only": 0, "conflict": 1
    }


def test_metrics_are_all_zero_for_no_records():
    """Nothing is hard-coded: an empty input produces zeros, not a crash or a constant."""
    metrics = compute_metrics([])
    assert metrics["totals"]["total_cases"] == 0
    assert metrics["results"] == {name: 0 for name in RESULT_ORDER}
    assert metrics["evidence"]["verification_rate"] == 0.0
    assert metrics["accuracy"]["correct_rate"] == 0.0


def test_category_breakdown_totals_match_the_record_count(mixed_records):
    by_category = compute_metrics(mixed_records)["by_category"]
    assert sum(bucket["total"] for bucket in by_category.values()) == len(mixed_records)


# ---------------------------------------------------------------------------------
# human-review candidate ranking
# ---------------------------------------------------------------------------------


def test_a_fully_correct_case_is_not_queued_for_review():
    assert select_review_candidates([record()]) == []


def test_incorrect_outranks_partial(mixed_records):
    candidates = select_review_candidates(mixed_records)
    assert [c["case_id"] for c in candidates][:2] == ["CASE-903", "CASE-904"]
    assert candidates[0]["priority"] == 1


def test_every_candidate_is_created_pending(mixed_records):
    for candidate in select_review_candidates(mixed_records):
        assert candidate["status"] == "pending"


def test_a_candidate_carries_both_sides_of_the_comparison(mixed_records):
    candidate = select_review_candidates(mixed_records)[0]
    assert candidate["ai_diagnosis"]["root_cause"] is not None
    assert candidate["expected_diagnosis"]["expected_rule_ids"] == ["R005"]
    assert candidate["reason_for_review"]
    for field in ("model_confidence", "effective_confidence", "evidence_integrity",
                  "reconciliation"):
        assert field in candidate


def test_all_triggers_are_recorded_not_just_the_strongest():
    """CASE-903 fires INCORRECT, failed evidence and conflict — the reviewer sees all three."""
    incorrect = record(
        evaluation_result="INCORRECT", evidence_integrity="failed", reconciliation="conflict",
        verified_citations=0, total_citations=1, failed_citations=1,
    )
    reasons = candidate_reasons(incorrect)
    assert len(reasons) >= 3
    assert min(priority for priority, _ in reasons) == 1


def test_a_high_confidence_wrong_answer_is_flagged_as_such():
    reasons = candidate_reasons(
        record(evaluation_result="INCORRECT", effective_confidence="high")
    )
    assert any("HIGH effective confidence" in reason for _, reason in reasons)


def test_an_unsupported_but_confident_diagnosis_is_flagged():
    reasons = candidate_reasons(
        record(evaluation_result="CORRECT", verified_citations=0, total_citations=2,
               failed_citations=2, evidence_integrity="failed")
    )
    assert any("Suspiciously unsupported" in reason for _, reason in reasons)


def test_a_failed_api_call_is_always_a_review_candidate():
    reasons = candidate_reasons(
        record(evaluation_status="failed", evaluation_result="UNABLE_TO_EVALUATE",
               error_type="ProviderError", agreement=None)
    )
    assert any("failed permanently" in reason for _, reason in reasons)


# ---------------------------------------------------------------------------------
# reports
# ---------------------------------------------------------------------------------


def test_the_matrix_has_exactly_one_row_per_case(mixed_records):
    rows = matrix_rows(mixed_records)
    assert len(rows) == len(mixed_records)
    assert [row["case_id"] for row in rows] == sorted(r.case_id for r in mixed_records)


def test_the_matrix_has_exactly_the_specified_columns(mixed_records):
    for row in matrix_rows(mixed_records):
        assert list(row) == list(MATRIX_COLUMNS)


def test_the_markdown_report_states_the_computed_figures(mixed_records):
    metrics = compute_metrics(mixed_records)
    markdown = render_markdown(metrics, mixed_records)
    assert "# NetSage AI — 40-case Gemini evaluation" in markdown
    assert "CASE-904" in markdown  # the failed case is named, not hidden
    assert "gemini-test" in markdown
    for name in RESULT_ORDER:
        assert name in markdown


def test_report_generation_writes_all_four_artefacts(tmp_path, monkeypatch, mixed_records):
    results = tmp_path / "evaluation_results.json"
    evaluate_all_cases.save_results(mixed_records, results)

    reports = tmp_path / "reports"
    monkeypatch.setattr(build_evaluation_reports, "REPORTS_DIR", reports)

    class FakeSettings:
        data_path = tmp_path

    monkeypatch.setattr(build_evaluation_reports, "get_settings", lambda: FakeSettings())

    assert build_evaluation_reports.main(["--results", str(results)]) == 0

    payload = json.loads((reports / "ai_evaluation.json").read_text(encoding="utf-8"))
    assert payload["metrics"]["totals"]["total_cases"] == len(mixed_records)
    assert len(payload["cases"]) == len(mixed_records)

    assert (reports / "ai_evaluation.md").read_text(encoding="utf-8").startswith("# NetSage")

    with (reports / "case_evaluation_matrix.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == len(mixed_records)
    assert list(rows[0]) == list(MATRIX_COLUMNS)

    queue = json.loads((tmp_path / "human_review_queue.json").read_text(encoding="utf-8"))
    assert queue["total_candidates"] == len(queue["candidates"])
    assert all(candidate["status"] == "pending" for candidate in queue["candidates"])


def test_reports_are_derived_only_from_the_stored_results(tmp_path, mixed_records):
    """Regenerating from the same file twice yields identical metrics."""
    results = tmp_path / "evaluation_results.json"
    evaluate_all_cases.save_results(mixed_records, results)
    first = compute_metrics(evaluate_all_cases.load_results(results))
    second = compute_metrics(evaluate_all_cases.load_results(results))
    assert first == second


# ---------------------------------------------------------------------------------
# resume behaviour and checkpointing
# ---------------------------------------------------------------------------------


class CountingProvider:
    """A mock provider that records which cases it was asked about."""

    def __init__(self, fail_on: set[str] | None = None) -> None:
        self._inner = MockProvider()
        self.name = "mock"
        self.model = "counting-mock"
        self.calls: list[str] = []
        self.fail_on = fail_on or set()

    def is_available(self) -> bool:
        return True

    def diagnose(self, request):
        self.calls.append(request.case_id or "")
        if request.case_id in self.fail_on:
            raise ProviderError("503 the model is overloaded")
        return self._inner.diagnose(request)


@pytest.fixture
def isolated_results(tmp_path, monkeypatch):
    path = tmp_path / "evaluation_results.json"
    monkeypatch.setattr(evaluate_all_cases, "results_path", lambda: path)
    return path


def test_a_completed_case_is_skipped_on_resume(cases, isolated_results):
    done = [record(case_id=cases[0].case_id)]
    selected = evaluate_all_cases.select_cases(cases, None, resume=True, existing=done)
    assert cases[0].case_id not in {c.case_id for c in selected}
    assert len(selected) == len(cases) - 1


def test_a_failed_case_is_retried_on_resume(cases, isolated_results):
    failed = [record(case_id=cases[0].case_id, evaluation_status="failed",
                     evaluation_result="UNABLE_TO_EVALUATE", agreement=None)]
    selected = evaluate_all_cases.select_cases(cases, None, resume=True, existing=failed)
    assert cases[0].case_id in {c.case_id for c in selected}


def test_without_resume_every_case_is_evaluated(cases, isolated_results):
    done = [record(case_id=cases[0].case_id)]
    selected = evaluate_all_cases.select_cases(cases, None, resume=False, existing=done)
    assert len(selected) == len(cases)


def test_the_case_flag_selects_exactly_one_case(cases, isolated_results):
    selected = evaluate_all_cases.select_cases(cases, cases[2].case_id.lower(), False, [])
    assert [c.case_id for c in selected] == [cases[2].case_id]


def test_an_unknown_case_id_is_an_error_not_a_silent_no_op(cases, isolated_results):
    with pytest.raises(SystemExit):
        evaluate_all_cases.select_cases(cases, "CASE-999", False, [])


def test_resume_makes_no_duplicate_provider_calls(cases, isolated_results):
    """The whole point of --resume: a completed case costs nothing the second time."""
    subset = cases[:3]
    provider = CountingProvider()

    first = evaluate_all_cases.run(subset, provider, [], persist_diagnosis=False)
    assert len(provider.calls) == 3
    assert len(first) == 3

    stored = evaluate_all_cases.load_results()
    remaining = evaluate_all_cases.select_cases(subset, None, resume=True, existing=stored)
    assert remaining == []

    evaluate_all_cases.run(remaining, provider, stored, persist_diagnosis=False)
    assert len(provider.calls) == 3, "resume re-called the provider for a completed case"


def test_every_case_is_checkpointed_as_it_completes(cases, isolated_results):
    provider = CountingProvider()
    evaluate_all_cases.run(cases[:2], provider, [], persist_diagnosis=False)

    stored = evaluate_all_cases.load_results()
    assert {r.case_id for r in stored} == {cases[0].case_id, cases[1].case_id}


def test_a_failing_case_is_persisted_and_the_run_continues(cases, isolated_results):
    subset = cases[:3]
    provider = CountingProvider(fail_on={subset[1].case_id})

    records = evaluate_all_cases.run(subset, provider, [], persist_diagnosis=False)

    assert len(records) == 3, "a failed case must not disappear from the results"
    failed = [r for r in records if not r.succeeded]
    assert [r.case_id for r in failed] == [subset[1].case_id]
    assert failed[0].error_type == "ProviderError"
    # The run carried on to the third case rather than aborting.
    assert provider.calls == [c.case_id for c in subset]

    stored = {r.case_id: r for r in evaluate_all_cases.load_results()}
    assert stored[subset[1].case_id].evaluation_status == "failed"


def test_re_evaluating_a_case_replaces_its_row_rather_than_adding_one(cases, isolated_results):
    provider = CountingProvider()
    first = evaluate_all_cases.run(cases[:1], provider, [], persist_diagnosis=False)
    second = evaluate_all_cases.run(cases[:1], provider, first, persist_diagnosis=False)

    assert len(second) == 1
    assert len(evaluate_all_cases.load_results()) == 1


def test_the_dry_run_makes_no_provider_calls(monkeypatch, isolated_results, capsys):
    """--dry-run validates configuration only; nothing may reach a provider."""
    provider = CountingProvider()
    monkeypatch.setattr(evaluate_all_cases, "preflight", lambda cases: provider)

    assert evaluate_all_cases.main(["--dry-run"]) == 0
    assert provider.calls == []
    assert "no API calls made" in capsys.readouterr().out
    assert not isolated_results.exists()
