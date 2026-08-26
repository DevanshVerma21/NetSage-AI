"""Dashboard and Responsible-AI metric tests.

Two things these tests are for. The first is arithmetic: every figure must be derived from
stored data, so an empty data directory has to produce zeros rather than the numbers that
happen to be true of the real dataset.

The second is the honesty property the phase brief demands, and it is the more important of
the two: an incomplete AI evaluation must not be presentable as a 40-case result. That is
asserted structurally — `accuracy` is `None` until coverage is complete, an invalidated
record counts as *not evaluated*, and the deterministic and AI blocks keep separate
denominators — so a future edit that reintroduces the problem fails here rather than in a
demo.

No test in this file calls a provider.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.app.config import get_settings
from backend.app.main import app
from backend.app.rules.engine import mandatory_rule_ids, registry
from backend.app.services import case_repo, dashboard as dashboard_service


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def empty_data_dir(tmp_path, monkeypatch):
    """Point the settings at an empty directory so nothing but zeros can be reported."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def _write_records(path, records):
    path.write_text(json.dumps(records), encoding="utf-8")


def _record(case_id, **overrides):
    """A minimally valid completed evaluation record."""
    base = {
        "case_id": case_id,
        "category": "VLAN",
        "severity": "High",
        "evaluation_status": "completed",
        "evaluation_result": "CORRECT",
        "evidence_integrity": "passed",
        "total_citations": 2,
        "verified_citations": 2,
        "failed_citations": 0,
        "model_confidence": "high",
        "effective_confidence": "high",
    }
    base.update(overrides)
    return base


# --- the deterministic block ---------------------------------------------------------------


def test_deterministic_counts_come_from_the_registry_and_the_case_file():
    summary = dashboard_service.deterministic_summary()

    assert summary["total_cases"] == len(case_repo.all_cases())
    assert summary["total_rules"] == len(registry())
    assert summary["mandatory_rules"] == len(mandatory_rule_ids())
    assert summary["mandatory_rules"] + summary["optional_rules"] == summary["total_rules"]


def test_no_rule_id_is_both_mandatory_and_optional():
    summary = dashboard_service.deterministic_summary()
    assert not set(summary["mandatory_rule_ids"]) & set(summary["optional_rule_ids"])


def test_the_golden_comparison_is_run_live_and_agrees_with_the_dataset():
    """Expected-vs-fired is recomputed here, not read from a log."""
    summary = dashboard_service.deterministic_summary()

    assert summary["cases_matching_expected_rules"] + summary["cases_not_matching"] == (
        summary["total_cases"]
    )
    assert summary["golden_case_result"] == "PASS"
    assert summary["mismatches"] == []
    assert summary["rule_pass_rate"] == 1.0


def test_the_rule_pass_rate_is_a_real_proportion():
    summary = dashboard_service.deterministic_summary()
    assert 0.0 <= summary["rule_pass_rate"] <= 1.0


# --- the AI block: coverage before accuracy ------------------------------------------------


def test_accuracy_is_withheld_while_coverage_is_incomplete():
    """The core requirement: one evaluated case is not a 40-case accuracy."""
    ai = dashboard_service.ai_evaluation_summary([dashboard_service.EvaluationRecord(**_record("CASE-001"))])

    assert ai["evaluated"] == 1
    assert ai["coverage_complete"] is False
    assert ai["accuracy"] is None
    assert "40-case" in ai["accuracy_note"] or "incomplete" in ai["accuracy_note"]


def test_an_invalidated_record_counts_as_not_evaluated():
    records = [
        dashboard_service.EvaluationRecord(
            **_record("CASE-001", invalidated=True, requires_rerun=True)
        )
    ]
    ai = dashboard_service.ai_evaluation_summary(records)

    assert ai["evaluated"] == 0
    assert ai["invalidated"] == 1
    assert ai["invalidated_case_ids"] == ["CASE-001"]
    assert ai["requires_rerun_case_ids"] == ["CASE-001"]
    assert ai["stored_records"] == 1, "the record is still stored, not deleted"


def test_a_failed_call_is_never_counted_as_an_evaluation():
    records = [
        dashboard_service.EvaluationRecord(
            **_record(
                "CASE-002",
                evaluation_status="failed",
                evaluation_result="UNABLE_TO_EVALUATE",
                error_type="quota",
            )
        )
    ]
    ai = dashboard_service.ai_evaluation_summary(records)

    assert ai["evaluated"] == 0
    assert ai["failed_calls"] == 1
    assert ai["failed_case_ids"] == ["CASE-002"]


def test_remaining_plus_evaluated_equals_the_case_total():
    records = [dashboard_service.EvaluationRecord(**_record("CASE-001"))]
    ai = dashboard_service.ai_evaluation_summary(records)

    assert ai["evaluated"] + ai["remaining"] == ai["total"]
    assert ai["pending"] == ai["remaining"]


def test_no_stored_result_reports_not_started_and_zero():
    ai = dashboard_service.ai_evaluation_summary([])

    assert ai["evaluated"] == 0
    assert ai["status"] == "NOT_STARTED"
    assert ai["accuracy"] is None
    assert ai["coverage_rate"] == 0.0
    assert "has not been run" in ai["headline"]


def test_attempted_but_unofficial_is_distinguished_from_never_run():
    records = [
        dashboard_service.EvaluationRecord(**_record("CASE-001", invalidated=True)),
        dashboard_service.EvaluationRecord(
            **_record("CASE-002", evaluation_status="failed", evaluation_result="UNABLE_TO_EVALUATE")
        ),
    ]
    ai = dashboard_service.ai_evaluation_summary(records)

    assert ai["status"] == "NOT_STARTED — Gemini quota limited"
    assert "Nothing was substituted" in ai["headline"]


def test_partial_coverage_reports_the_quota_limited_status():
    records = [
        dashboard_service.EvaluationRecord(**_record(f"CASE-{i:03d}")) for i in range(1, 4)
    ]
    ai = dashboard_service.ai_evaluation_summary(records)

    assert ai["evaluated"] == 3
    assert ai["status"] == "PARTIAL — Gemini quota limited"
    assert ai["accuracy"] is None


def test_complete_coverage_releases_accuracy():
    """The withholding is a function of coverage, not a permanent refusal."""
    ids = [case.case_id for case in case_repo.all_cases()]
    records = [dashboard_service.EvaluationRecord(**_record(cid)) for cid in ids]
    ai = dashboard_service.ai_evaluation_summary(records)

    assert ai["coverage_complete"] is True
    assert ai["status"] == "COMPLETE"
    assert ai["accuracy"] is not None
    assert ai["accuracy"]["correct_rate"] == 1.0


def test_invalidated_records_cannot_enter_the_accuracy_denominator():
    """Full coverage of official records, plus one invalidated row on top."""
    ids = [case.case_id for case in case_repo.all_cases()]
    records = [dashboard_service.EvaluationRecord(**_record(cid)) for cid in ids]
    records.append(
        dashboard_service.EvaluationRecord(
            **_record(ids[0], evaluation_result="INCORRECT", invalidated=True)
        )
    )
    ai = dashboard_service.ai_evaluation_summary(records)

    assert ai["evaluated"] == len(ids)
    assert ai["results"]["INCORRECT"] == 0, "an invalidated row leaked into the metrics"
    assert ai["accuracy"]["correct_rate"] == 1.0


# --- loading is tolerant, never fatal ------------------------------------------------------


def test_a_missing_results_file_yields_no_records(empty_data_dir):
    assert dashboard_service.load_evaluation_records() == []


def test_a_malformed_results_file_yields_no_records(empty_data_dir):
    (empty_data_dir / dashboard_service.RESULTS_FILE).write_text("not json", encoding="utf-8")
    assert dashboard_service.load_evaluation_records() == []


def test_an_unparseable_row_is_skipped_not_fatal(empty_data_dir):
    _write_records(
        empty_data_dir / dashboard_service.RESULTS_FILE,
        [{"nonsense": True}, _record("CASE-001")],
    )
    records = dashboard_service.load_evaluation_records()
    assert [r.case_id for r in records] == ["CASE-001"]


# --- the human-review block ----------------------------------------------------------------


def test_human_review_reports_zero_and_says_it_is_incomplete(empty_data_dir):
    review = dashboard_service.human_review_summary()

    assert review["total_reviews"] == 0
    assert review["corrections"] == 0
    assert review["corrections_complete"] is False
    assert review["incomplete_message"] == "Human review data incomplete"


def test_the_correction_requirement_is_never_reported_as_met_by_a_target(empty_data_dir):
    review = dashboard_service.human_review_summary()
    assert review["required_corrections"] == dashboard_service.REQUIRED_CORRECTIONS
    assert review["corrections"] <= review["required_corrections"] or review["corrections_complete"]


def test_an_absent_log_is_an_empty_state_not_examples(empty_data_dir):
    log = dashboard_service.responsible_ai_log()

    assert log["available"] is False
    assert log["corrections"] == []
    assert log["total_corrections"] == 0
    assert "No genuine human correction" in log["empty_state"]


def test_a_present_log_is_exposed_as_stored(empty_data_dir):
    payload = {
        "generated_at": "2026-01-01T00:00:00Z",
        "source": "human_review_queue",
        "corrections": [
            {
                "case_id": "CASE-007",
                "ai_output": "trunk misconfiguration",
                "human_decision": "edited",
                "correction": "the ACL denies the flow",
                "reason": "wrong_layer",
                "lesson": "a permitted VLAN is not a permitted flow",
            }
        ],
    }
    (empty_data_dir / dashboard_service.RESPONSIBLE_AI_LOG).write_text(
        json.dumps(payload), encoding="utf-8"
    )
    log = dashboard_service.responsible_ai_log()

    assert log["available"] is True
    assert log["total_corrections"] == 1
    assert log["corrections"][0]["case_id"] == "CASE-007"
    assert log["empty_state"] is None


# --- the composed payloads -----------------------------------------------------------------


def test_the_dashboard_keeps_the_two_halves_apart():
    payload = dashboard_service.dashboard()

    assert set(payload) == {"deterministic", "ai_evaluation", "human_review", "separation_note"}
    assert "never combined" in payload["separation_note"]
    # No merged score exists anywhere in the payload.
    assert "overall_accuracy" not in json.dumps(payload)


def test_responsible_ai_carries_every_required_disclosure():
    payload = dashboard_service.responsible_ai()

    assert set(payload) == {
        "ai_evaluation",
        "human_review",
        "log",
        "methodology",
        "execution_scope",
        "limitations",
    }
    method = payload["methodology"]
    assert method["pipeline"] and method["grading"]
    assert method["human_review"]["mandatory"] is True
    assert method["evidence_verification"]["statuses"] == ["passed", "partial", "failed"]
    assert method["confidence_capping"]["triggers"]
    assert method["prompts"]["diagnose_prompt"]["version"]
    assert len(method["prompts"]["diagnose_prompt"]["sha256"]) == 64


def test_the_execution_scope_denies_device_access():
    scope = dashboard_service.responsible_ai()["execution_scope"]
    joined = " ".join(scope["cannot"]).lower()

    assert "ssh" in joined and "telnet" in joined
    assert "no fix" in joined or "apply" in joined
    assert "bypass the human review gate" in joined


def test_the_limitations_lead_with_the_real_blockers(empty_data_dir):
    payload = dashboard_service.responsible_ai()
    titles = [item["title"] for item in payload["limitations"]]

    assert titles[0] == "AI evaluation is incomplete"
    assert "Human review data incomplete" in titles
    assert all(item["severity"] in {"high", "medium", "low"} for item in payload["limitations"])


def test_a_complete_evaluation_drops_the_incompleteness_limitation(monkeypatch):
    ids = [case.case_id for case in case_repo.all_cases()]
    records = [dashboard_service.EvaluationRecord(**_record(cid)) for cid in ids]
    monkeypatch.setattr(dashboard_service, "load_evaluation_records", lambda *a, **k: records)

    titles = [item["title"] for item in dashboard_service.responsible_ai()["limitations"]]
    assert "AI evaluation is incomplete" not in titles


# --- the API surface -----------------------------------------------------------------------


def test_the_dashboard_endpoint_returns_the_service_payload(client):
    response = client.get("/api/dashboard")

    assert response.status_code == 200
    body = response.json()
    assert body["deterministic"]["total_cases"] == len(case_repo.all_cases())
    assert body["ai_evaluation"]["evaluated"] <= body["ai_evaluation"]["total"]


def test_the_responsible_ai_endpoint_returns_the_service_payload(client):
    response = client.get("/api/responsible-ai")

    assert response.status_code == 200
    body = response.json()
    assert body["limitations"]
    assert body["execution_scope"]["scope"]


def test_the_evaluations_endpoint_filters_by_case_id(client):
    response = client.get("/api/evaluations", params={"case_id": "CASE-999"})

    assert response.status_code == 200
    assert response.json() == []


def test_the_evaluations_endpoint_returns_a_list(client):
    response = client.get("/api/evaluations")

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_no_endpoint_leaks_a_credential_or_an_environment_variable(client):
    """The dashboard reads settings; it must not report them."""
    for path in ("/api/dashboard", "/api/responsible-ai", "/api/evaluations"):
        text = client.get(path).text.lower()
        for forbidden in ("gemini_api_key", "anthropic_api_key", "api_key", "sk-ant", "aiza"):
            assert forbidden not in text, f"{path} mentions {forbidden}"
