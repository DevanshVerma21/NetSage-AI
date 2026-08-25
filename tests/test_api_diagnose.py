"""Phase 3 — ``POST /api/diagnose`` and the diagnosis record store.

The central assertion in this file is a negative one: there is no request, and no
combination of parameters, that produces a diagnosis which is anything other than
``awaiting_human_review`` with ``applied=false``. Everything else here is provenance and
the independent checks travelling with the stored record.

Every test uses the mock provider. Nothing in this file makes a network call.
"""

from __future__ import annotations

import json

from backend.app.models.records import AWAITING_HUMAN_REVIEW
from backend.app.services.record_store import DIAGNOSES_FILE


def test_diagnose_creates_a_record_awaiting_human_review(client):
    response = client.post("/api/diagnose", json={"case_id": "CASE-001", "provider": "mock"})
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == AWAITING_HUMAN_REVIEW
    assert body["applied"] is False
    assert body["review_id"] is None
    assert body["diagnosis_id"].startswith("DIAG-")


def test_no_parameter_can_pre_approve_a_diagnosis(client):
    """The request model forbids extras, so a client cannot smuggle in a verdict."""
    for smuggled in (
        {"status": "accepted"},
        {"applied": True},
        {"review_id": "REV-000000000000"},
        {"verdict": "accepted"},
        {"mutations": [{"type": "add_vlan", "device": "SW1", "vlan_id": 99}]},
    ):
        body = {"case_id": "CASE-001", "provider": "mock", **smuggled}
        response = client.post("/api/diagnose", json=body)
        assert response.status_code == 422, f"{smuggled} was not rejected"


def test_the_diagnosis_carries_full_provenance(client, diagnosed):
    for field in ("provider", "model", "prompt_name", "prompt_version", "prompt_sha256"):
        assert diagnosed[field], f"{field} must identify what produced this proposal"
    assert diagnosed["provider"] == "mock"
    assert len(diagnosed["prompt_sha256"]) == 64


def test_the_diagnosis_carries_the_deterministic_findings(client, diagnosed):
    rule_ids = sorted({finding["rule_id"] for finding in diagnosed["rule_findings"]})
    assert rule_ids == ["R004", "R005", "R006"]
    checked = client.post("/api/rules/check", json={"case_id": "CASE-001"}).json()
    assert rule_ids == checked["rule_ids"], "one engine, not two"


def test_the_independent_checks_are_stored(client, diagnosed):
    integrity = diagnosed["evidence_integrity"]
    assert integrity["status"] in ("passed", "partial", "failed")
    # A failed citation is kept, never quietly dropped.
    assert integrity["failed_count"] == len(integrity["failed_items"])

    assert diagnosed["reconciliation"]["status"]
    confidence = diagnosed["confidence"]
    assert confidence["model_confidence"] and confidence["effective_confidence"]
    assert isinstance(confidence["was_capped"], bool)


def test_model_and_effective_confidence_stay_separate(client, diagnosed):
    confidence = diagnosed["confidence"]
    assert "model_confidence" in confidence and "effective_confidence" in confidence
    if confidence["was_capped"]:
        assert confidence["cap_reasons"]
        assert confidence["effective_confidence_score"] <= confidence["model_confidence_score"]


def test_diagnose_persists_across_a_new_client(client, isolated_store, diagnosed):
    """The record is on disk, not in process memory."""
    stored = json.loads((isolated_store / DIAGNOSES_FILE).read_text(encoding="utf-8"))
    assert [record["diagnosis_id"] for record in stored] == [diagnosed["diagnosis_id"]]
    assert stored[0]["applied"] is False
    assert stored[0]["status"] == AWAITING_HUMAN_REVIEW


def test_missing_records_file_is_not_an_error(client, isolated_store):
    """A fresh checkout has no data/diagnoses.json. Listing must still work."""
    assert not (isolated_store / DIAGNOSES_FILE).exists()
    assert client.get("/api/diagnoses").json() == []


def test_list_and_get_diagnoses(client, diagnosed):
    listed = client.get("/api/diagnoses").json()
    assert [record["diagnosis_id"] for record in listed] == [diagnosed["diagnosis_id"]]

    by_case = client.get("/api/diagnoses", params={"case_id": "CASE-001"}).json()
    assert len(by_case) == 1
    assert client.get("/api/diagnoses", params={"case_id": "CASE-777"}).json() == []

    awaiting = client.get("/api/diagnoses", params={"status": AWAITING_HUMAN_REVIEW}).json()
    assert len(awaiting) == 1
    assert client.get("/api/diagnoses", params={"status": "accepted"}).json() == []

    one = client.get(f"/api/diagnoses/{diagnosed['diagnosis_id']}").json()
    assert one == diagnosed


def test_unknown_diagnosis_is_404(client):
    response = client.get("/api/diagnoses/DIAG-000000000000")
    assert response.status_code == 404
    assert "DIAG-000000000000" in response.json()["detail"]


def test_diagnose_on_an_unknown_case_is_404(client):
    response = client.post("/api/diagnose", json={"case_id": "CASE-404", "provider": "mock"})
    assert response.status_code == 404


def test_diagnose_response_contains_no_credential(client, diagnosed):
    raw = json.dumps(diagnosed)
    assert "api_key" not in raw.lower()
    assert "AIza" not in raw
    for env_name in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "NETSAGE_"):
        assert env_name not in raw


def test_two_diagnoses_of_the_same_case_are_both_stored(client):
    first = client.post("/api/diagnose", json={"case_id": "CASE-001", "provider": "mock"}).json()
    second = client.post("/api/diagnose", json={"case_id": "CASE-001", "provider": "mock"}).json()
    assert first["diagnosis_id"] != second["diagnosis_id"]
    assert len(client.get("/api/diagnoses").json()) == 2
    assert all(record["applied"] is False for record in client.get("/api/diagnoses").json())
