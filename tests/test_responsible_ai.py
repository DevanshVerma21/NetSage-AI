"""Phase 6 §13 — the Responsible-AI log is built from stored reviews, never invented.

Every review used here is created through ``review_service`` inside a temporary store, exactly
as the interactive tool would create it. What these tests actually pin down is the integrity
contract: fewer than five genuine corrections produces *no file at all*, accepted reviews are
not corrections, and the AI's proposal and the human's correction stay in separate fields.

No Gemini call happens in this module.
"""

from __future__ import annotations

import json

import pytest

from backend.app.services import diagnosis_repo, review_service
from backend.app.services.diagnose import diagnose_case
from backend.app.services.evaluation import record_from_result
from backend.app.services.case_repo import load_cases
from backend.scripts import build_responsible_ai as builder


@pytest.fixture
def cases():
    return load_cases()


@pytest.fixture
def paths(tmp_path):
    return tmp_path / "responsible_ai_log.json", tmp_path / "RESPONSIBLE_AI.md"


def _diagnose(case, provider="gemini"):
    """One persisted diagnosis plus its evaluation record.

    The pipeline is driven by the mock provider — no test in this file may call a model — but the
    stored record is relabelled with a real provider name by default, because the builder now
    refuses to count a correction whose diagnosis came from a fixture. These tests are about the
    builder's *mechanics*, so they need a record that is eligible; the exclusion itself is
    asserted separately by the tests at the end of this module, which keep ``provider="mock"``.
    """
    from backend.app.ai.mock_provider import MockProvider

    result = diagnose_case(case, provider=MockProvider())
    record = diagnosis_repo.save(result)
    if provider != record.provider:
        record = diagnosis_repo.collection.update(
            record.model_copy(update={"provider": provider, "model": f"{provider}-3.6-flash"})
        )
    return record, record_from_result(case, result, diagnosis_id=record.diagnosis_id)


def _seed(cases, count, verdict="edited", provider="gemini"):
    """`count` genuine corrections, each on its own case. Returns evaluation records."""
    evaluations = {}
    for case in cases[:count]:
        record, evaluation = _diagnose(case, provider=provider)
        payload = {"verdict": verdict, "reviewer": "test-reviewer"}
        if verdict == "edited":
            payload["corrected_root_cause"] = f"the real fault in {case.case_id}"
            payload["reason_code"] = "wrong_root_cause"
        elif verdict == "rejected":
            payload["reason_code"] = "unsupported_evidence"
            payload["notes"] = "the citations are not in the supplied output"
        review_service.create_review(diagnosis_id=record.diagnosis_id, **payload)
        evaluations[evaluation.case_id.upper()] = evaluation
    return evaluations


# --- the threshold -------------------------------------------------------------------------


def test_no_reviews_at_all_writes_nothing_and_fails(isolated_store, paths, capsys):
    log_path, doc_path = paths
    exit_code = builder.main(["--log-path", str(log_path), "--doc-path", str(doc_path)])
    assert exit_code == 1
    assert not log_path.exists()
    assert not doc_path.exists()
    assert "0 genuine human correction" in capsys.readouterr().err


def test_four_corrections_are_not_enough(isolated_store, cases, paths):
    _seed(cases, 4)
    log_path, doc_path = paths
    assert builder.main(["--log-path", str(log_path), "--doc-path", str(doc_path)]) == 1
    assert not log_path.exists()


def test_accepted_reviews_do_not_count_as_corrections(isolated_store, cases, paths):
    _seed(cases, 8, verdict="accepted")
    assert builder.corrections() == []
    log_path, doc_path = paths
    assert builder.main(["--log-path", str(log_path), "--doc-path", str(doc_path)]) == 1


def test_five_corrections_produce_the_log(isolated_store, cases, paths, monkeypatch):
    evaluations = _seed(cases, 5)
    monkeypatch.setattr(builder, "load_results", lambda: list(evaluations.values()))
    log_path, doc_path = paths

    assert builder.main(["--log-path", str(log_path), "--doc-path", str(doc_path)]) == 0

    payload = json.loads(log_path.read_text(encoding="utf-8"))
    assert payload["total_corrections"] == 5
    assert payload["required_corrections"] == 5
    assert len(payload["corrections"]) == 5
    assert doc_path.exists()


def test_rejected_reviews_count_as_corrections(isolated_store, cases):
    _seed(cases, 5, verdict="rejected")
    assert len(builder.corrections()) == 5


# --- separation of AI output from human correction -----------------------------------------


def test_ai_and_human_fields_are_separate(isolated_store, cases):
    evaluations = _seed(cases, 5)
    entries = builder.build_entries(builder.corrections(), evaluations)

    for entry in entries:
        ai = entry["ai_diagnosis"]
        corrected = entry["corrected_diagnosis"]
        assert ai["root_cause"], "the AI proposal must survive in the log"
        assert corrected["root_cause"].startswith("the real fault in")
        assert ai["root_cause"] != corrected["root_cause"]
        assert entry["human_decision"] == "edited"
        assert entry["reason_code"] == "wrong_root_cause"
        assert entry["applied"] is False, "documenting a correction must not apply anything"


def test_every_required_field_is_present(isolated_store, cases):
    evaluations = _seed(cases, 5)
    entries = builder.build_entries(builder.corrections(), evaluations)
    required = {
        "case_id",
        "ai_diagnosis",
        "model_confidence",
        "effective_confidence",
        "evidence",
        "evidence_integrity",
        "human_decision",
        "corrected_diagnosis",
        "reason_code",
        "human_notes",
        "lesson",
        "timestamp",
    }
    for entry in entries:
        assert required <= set(entry), sorted(required - set(entry))


def test_the_lesson_is_labelled_as_derived(isolated_store, cases):
    evaluations = _seed(cases, 5)
    entries = builder.build_entries(builder.corrections(), evaluations)
    for entry in entries:
        assert entry["lesson"]
        assert "derived" in entry["lesson_source"]


def test_a_missing_evaluation_record_leaves_nulls_rather_than_guesses(isolated_store, cases):
    _seed(cases, 5)
    entries = builder.build_entries(builder.corrections(), {})
    for entry in entries:
        assert entry["model_confidence"] is None
        assert entry["evidence"] == []
        assert entry["evaluation_result"] is None
        assert entry["human_decision"] == "edited", "the human record is still complete"


# --- markdown ------------------------------------------------------------------------------


def test_markdown_reports_the_real_counts(isolated_store, cases):
    evaluations = _seed(cases, 5)
    entries = builder.build_entries(builder.corrections(), evaluations)
    markdown = builder.render_markdown(builder.build_payload(entries))

    assert "| corrections documented (edited + rejected) | 5 |" in markdown
    for entry in entries:
        assert entry["case_id"] in markdown
    assert "EDITED" in markdown


# --- a fixture is not evidence about a model -----------------------------------------------
#
# The point of these tests is the one thing the correction count must never be allowed to mean:
# "a person disagreed with something the machine generated locally". Correcting a mock answer is
# a real review — the gate applies to every diagnosis — but it teaches nothing about the model,
# so it cannot move the counter toward the Responsible-AI requirement.


def test_a_mock_diagnosis_is_not_a_genuine_model_output(isolated_store, cases):
    record, _ = _diagnose(cases[0], provider="mock")
    assert review_service.is_genuine_model_diagnosis(record) is False


def test_a_gemini_diagnosis_is_a_genuine_model_output(isolated_store, cases):
    record, _ = _diagnose(cases[0], provider="gemini")
    assert review_service.is_genuine_model_diagnosis(record) is True


def test_a_correction_with_no_stored_diagnosis_is_not_genuine():
    assert review_service.is_genuine_model_diagnosis(None) is False


def test_corrections_on_mock_diagnoses_do_not_count(isolated_store, cases):
    _seed(cases, 5, provider="mock")

    assert len(review_service.all_records()) == 5, "the reviews were genuinely recorded"
    assert builder.corrections() == [], "but none of them counts as a correction"
    assert len(builder.excluded_corrections()) == 5


def test_the_builder_refuses_to_write_from_mock_corrections(isolated_store, cases, paths):
    _seed(cases, 5, provider="mock")
    log_path, doc_path = paths

    assert builder.main(["--log-path", str(log_path), "--doc-path", str(doc_path)]) == 1
    assert not log_path.exists(), "five mock corrections must not produce a log"


def test_the_dashboard_and_the_builder_agree_on_the_count(isolated_store, cases):
    """The failure this prevents: a 5/5 headline over a file the builder refused to write."""
    from backend.app.services import dashboard

    _seed(cases, 3, provider="mock")
    _seed(cases[3:], 2, provider="gemini")

    review = dashboard.human_review_summary()
    assert review["total_reviews"] == 5
    assert review["corrections"] == len(builder.corrections()) == 2
    assert review["corrections_excluded_as_synthetic"] == 3
    assert review["corrections_complete"] is False
    assert review["incomplete_message"] == "Human review data incomplete"
