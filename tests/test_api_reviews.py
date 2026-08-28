"""Phase 3 — ``POST /api/reviews``: the human gate itself.

Each verdict carries a different evidentiary burden, and the tests treat those burdens as
the contract: an "edited" review that records no correction is not a review, and a bare
"rejected" teaches the Responsible-AI log nothing. Both must be refused with 422.

The agreement record is asserted here too, because the dashboard's AI-vs-human metric is
required to be computed from these stored values rather than hard-coded anywhere.
"""

from __future__ import annotations

from backend.app.services import diagnosis_repo, review_service


def _review(client, diagnosis_id: str, **kwargs):
    body = {"diagnosis_id": diagnosis_id, **kwargs}
    return client.post("/api/reviews", json=body)


# --- accepted -----------------------------------------------------------------------------


def test_accepted_review_needs_no_reason_code(client, diagnosed):
    response = _review(client, diagnosed["diagnosis_id"], verdict="accepted")
    assert response.status_code == 201
    body = response.json()
    assert body["review_id"].startswith("REV-")
    assert body["verdict"] == "accepted"
    assert body["agreement"] == {"root_cause": True, "osi_layer": True, "category": True}


def test_a_review_moves_the_diagnosis_but_does_not_apply_it(client, diagnosed):
    review = _review(client, diagnosed["diagnosis_id"], verdict="accepted").json()
    stored = client.get(f"/api/diagnoses/{diagnosed['diagnosis_id']}").json()
    assert stored["status"] == "accepted"
    assert stored["review_id"] == review["review_id"]
    assert stored["applied"] is False, "approval is not application"


# --- edited -------------------------------------------------------------------------------


def test_edited_review_requires_a_reason_code(client, diagnosed):
    response = _review(
        client,
        diagnosed["diagnosis_id"],
        verdict="edited",
        corrected_root_cause="VLAN 30 was never created on SW1",
    )
    assert response.status_code == 422
    assert "reason_code" in response.json()["detail"]


def test_edited_review_requires_at_least_one_correction(client, diagnosed):
    response = _review(
        client, diagnosed["diagnosis_id"], verdict="edited", reason_code="wrong_layer"
    )
    assert response.status_code == 422
    assert "correction" in response.json()["detail"]


def test_edited_review_records_field_level_disagreement(client, diagnosed):
    response = _review(
        client,
        diagnosed["diagnosis_id"],
        verdict="edited",
        reason_code="incomplete_root_cause",
        corrected_root_cause="VLAN 30 missing from the SW1 VLAN database",
        corrected_fix_steps=["vlan 30", "name VLAN30", "interface Vlan30", "no shutdown"],
    )
    assert response.status_code == 201
    agreement = response.json()["agreement"]
    assert agreement["root_cause"] is False, "the reviewer supplied a different cause"
    assert agreement["osi_layer"] is True, "not corrected, so left standing"
    assert agreement["category"] is True


def test_edited_review_rejects_an_invalid_corrected_enum(client, diagnosed):
    for field, value in (("corrected_osi_layer", "L9"), ("corrected_category", "NOT_A_TAG")):
        response = _review(
            client,
            diagnosed["diagnosis_id"],
            verdict="edited",
            reason_code="wrong_classification",
            **{field: value},
        )
        assert response.status_code == 422
        assert value in response.json()["detail"]


def test_a_reviewer_can_narrow_the_fix_but_not_invent_findings(client, diagnosed):
    response = _review(
        client,
        diagnosed["diagnosis_id"],
        verdict="edited",
        reason_code="scope_reduced",
        corrected_fix_steps=["vlan 30"],
        corrected_rule_ids=["R005"],
    )
    assert response.status_code == 201
    assert response.json()["corrected_rule_ids"] == ["R005"]


def test_corrected_rule_ids_must_come_from_this_diagnosis(client, diagnosed):
    response = _review(
        client,
        diagnosed["diagnosis_id"],
        verdict="edited",
        reason_code="scope_reduced",
        corrected_fix_steps=["vlan 30"],
        corrected_rule_ids=["R001"],
    )
    assert response.status_code == 422
    assert "R001" in response.json()["detail"]


# --- rejected -----------------------------------------------------------------------------


def test_rejected_review_requires_reason_code_and_notes(client, diagnosed):
    bare = _review(client, diagnosed["diagnosis_id"], verdict="rejected")
    assert bare.status_code == 422
    assert "reason_code" in bare.json()["detail"]

    no_notes = _review(
        client, diagnosed["diagnosis_id"], verdict="rejected", reason_code="hallucinated_evidence"
    )
    assert no_notes.status_code == 422
    assert "notes" in no_notes.json()["detail"]


def test_rejected_review_is_recorded_as_a_root_cause_disagreement(client, diagnosed):
    response = _review(
        client,
        diagnosed["diagnosis_id"],
        verdict="rejected",
        reason_code="hallucinated_evidence",
        notes="The cited line does not appear in the supplied show output.",
    )
    assert response.status_code == 201
    assert response.json()["agreement"]["root_cause"] is False
    stored = client.get(f"/api/diagnoses/{diagnosed['diagnosis_id']}").json()
    assert stored["status"] == "rejected"
    assert stored["applied"] is False


# --- shape and lookups --------------------------------------------------------------------


def test_unknown_verdict_is_422(client, diagnosed):
    assert _review(client, diagnosed["diagnosis_id"], verdict="approved").status_code == 422
    assert _review(client, diagnosed["diagnosis_id"], verdict="").status_code == 422


def test_review_of_an_unknown_diagnosis_is_404(client):
    response = _review(client, "DIAG-000000000000", verdict="accepted")
    assert response.status_code == 404


def test_a_second_review_of_the_same_diagnosis_is_409(client, diagnosed):
    assert _review(client, diagnosed["diagnosis_id"], verdict="accepted").status_code == 201
    again = _review(
        client,
        diagnosed["diagnosis_id"],
        verdict="rejected",
        reason_code="changed_my_mind",
        notes="Trying to overwrite the audit trail.",
    )
    assert again.status_code == 409
    assert "already been reviewed" in again.json()["detail"]


def test_review_bodies_cannot_carry_a_mutation(client, diagnosed):
    response = client.post(
        "/api/reviews",
        json={
            "diagnosis_id": diagnosed["diagnosis_id"],
            "verdict": "accepted",
            "mutations": [{"type": "add_vlan", "device": "SW1", "vlan_id": 99}],
        },
    )
    assert response.status_code == 422


def test_list_and_get_reviews(client, diagnosed):
    review = _review(client, diagnosed["diagnosis_id"], verdict="accepted").json()

    assert [r["review_id"] for r in client.get("/api/reviews").json()] == [review["review_id"]]
    by_diagnosis = client.get(
        "/api/reviews", params={"diagnosis_id": diagnosed["diagnosis_id"]}
    ).json()
    assert len(by_diagnosis) == 1
    assert len(client.get("/api/reviews", params={"verdict": "accepted"}).json()) == 1
    assert client.get("/api/reviews", params={"verdict": "rejected"}).json() == []
    assert client.get("/api/reviews", params={"verdict": "nonsense"}).status_code == 422

    assert client.get(f"/api/reviews/{review['review_id']}").json() == review
    assert client.get("/api/reviews/REV-000000000000").status_code == 404


def test_agreement_stats_are_computed_from_the_stored_reviews(client):
    """The dashboard metric must be derived, never hard-coded."""
    assert review_service.agreement_stats()["total"] == 0

    for verdict, extra in (
        ("accepted", {}),
        ("rejected", {"reason_code": "wrong_cause", "notes": "Not what the output shows."}),
        ("edited", {"reason_code": "narrowed", "corrected_root_cause": "Missing VLAN 30."}),
    ):
        diagnosis = client.post(
            "/api/diagnose", json={"case_id": "CASE-001", "provider": "mock"}
        ).json()
        assert _review(
            client, diagnosis["diagnosis_id"], verdict=verdict, **extra
        ).status_code == 201

    stats = review_service.agreement_stats()
    assert stats["total"] == 3
    assert stats["accepted"] == 1 and stats["edited"] == 1 and stats["rejected"] == 1
    assert stats["full_agreement"] == 1
    assert stats["root_cause_disagreement"] == 2


def test_review_candidates_include_only_stored_pending_genuine_diagnoses(client, diagnosed):
    assert client.get("/api/review-candidates").json() == []

    record = diagnosis_repo.require(diagnosed["diagnosis_id"])
    diagnosis_repo.collection.update(record.model_copy(update={"provider": "gemini"}))

    candidates = client.get("/api/review-candidates").json()
    assert len(candidates) == 1
    assert candidates[0]["diagnosis_id"] == diagnosed["diagnosis_id"]
    assert candidates[0]["provider"] == "gemini"
    assert candidates[0]["expected_fault"]
    assert candidates[0]["symptom"]


def test_genuine_correction_is_read_from_stored_review_records(client, diagnosed):
    record = diagnosis_repo.require(diagnosed["diagnosis_id"])
    diagnosis_repo.collection.update(record.model_copy(update={"provider": "gemini"}))
    response = _review(
        client,
        diagnosed["diagnosis_id"],
        verdict="edited",
        reason_code="wrong_cause",
        notes="The cited evidence supports a different conclusion.",
        corrected_root_cause="The switch configuration does not match the intended VLAN.",
    )
    assert response.status_code == 201

    payload = client.get("/api/responsible-ai").json()
    assert payload["human_review"]["accepted"] == 0
    assert payload["human_review"]["edited"] == 1
    assert payload["human_review"]["corrections"] == 1
    assert payload["log"]["source"] == "stored_review_records"
    assert payload["log"]["corrections"][0]["case_id"] == diagnosed["case_id"]
