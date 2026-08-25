"""Phase 3 — ``POST /api/fixes/apply``: the four refusals, and the honesty of a fix run.

This is the security file. It asserts the gate from the outside, over HTTP, the way a
frontend would meet it:

* apply with no review at all → 409
* apply a rejected diagnosis → 409
* apply the same diagnosis twice → 409
* name somebody else's approval → the server still resolves review → diagnosis

and it asserts that nothing a client sends can describe a change: the mutations come from
the stored deterministic findings or they do not happen.
"""

from __future__ import annotations

import json

from backend.app.models.records import EXECUTION_SCOPE, SIMULATION_DISCLAIMER
from backend.app.services import case_repo


def _accept(client, diagnosis_id: str):
    response = client.post(
        "/api/reviews", json={"diagnosis_id": diagnosis_id, "verdict": "accepted"}
    )
    assert response.status_code == 201, response.text
    return response.json()


# --- the refusals -------------------------------------------------------------------------


def test_a_fix_without_any_review_is_409(client, diagnosed):
    response = client.post("/api/fixes/apply", json={"diagnosis_id": diagnosed["diagnosis_id"]})
    assert response.status_code == 409
    assert "human review is required" in response.json()["detail"]
    assert client.get(f"/api/diagnoses/{diagnosed['diagnosis_id']}").json()["applied"] is False


def test_a_rejected_diagnosis_can_never_be_applied(client, diagnosed):
    review = client.post(
        "/api/reviews",
        json={
            "diagnosis_id": diagnosed["diagnosis_id"],
            "verdict": "rejected",
            "reason_code": "hallucinated_evidence",
            "notes": "The cited interface is not in the supplied output.",
        },
    ).json()

    by_review = client.post("/api/fixes/apply", json={"review_id": review["review_id"]})
    assert by_review.status_code == 409
    assert "rejected" in by_review.json()["detail"]

    # The same refusal by the other route in — a rejection is not a loophole either way.
    by_diagnosis = client.post(
        "/api/fixes/apply", json={"diagnosis_id": diagnosed["diagnosis_id"]}
    )
    assert by_diagnosis.status_code == 409

    stored = client.get(f"/api/diagnoses/{diagnosed['diagnosis_id']}").json()
    assert stored["applied"] is False
    assert client.get("/api/fixes").json() == []


def test_applying_twice_is_409(client, diagnosed):
    review = _accept(client, diagnosed["diagnosis_id"])
    assert client.post("/api/fixes/apply", json={"review_id": review["review_id"]}).status_code == 201

    again = client.post("/api/fixes/apply", json={"review_id": review["review_id"]})
    assert again.status_code == 409
    assert "already had a fix applied" in again.json()["detail"]
    assert len(client.get("/api/fixes").json()) == 1


def test_an_unknown_review_is_404(client):
    response = client.post("/api/fixes/apply", json={"review_id": "REV-000000000000"})
    assert response.status_code == 404


def test_the_request_must_name_exactly_one_record(client, diagnosed):
    assert client.post("/api/fixes/apply", json={}).status_code == 422
    both = client.post(
        "/api/fixes/apply",
        json={"review_id": "REV-000000000000", "diagnosis_id": diagnosed["diagnosis_id"]},
    )
    assert both.status_code == 422


def test_a_client_cannot_describe_the_fix(client, diagnosed):
    """No request shape accepts a mutation, a command, or a target device."""
    review = _accept(client, diagnosed["diagnosis_id"])
    for smuggled in (
        {"mutations": [{"type": "add_vlan", "device": "SW1", "vlan_id": 999}]},
        {"commands": ["no shutdown"]},
        {"device": "SW1"},
        {"lab_state": {}},
        {"execution_scope": "physical_hardware"},
    ):
        response = client.post(
            "/api/fixes/apply", json={"review_id": review["review_id"], **smuggled}
        )
        assert response.status_code == 422, f"{smuggled} was not rejected"
    assert client.get("/api/fixes").json() == [], "no fix ran on any of those attempts"


# --- the permitted path -------------------------------------------------------------------


def test_an_accepted_diagnosis_applies_and_verifies(client, diagnosed):
    review = _accept(client, diagnosed["diagnosis_id"])
    response = client.post("/api/fixes/apply", json={"review_id": review["review_id"]})
    assert response.status_code == 201
    run = response.json()

    assert run["diagnosis_id"] == diagnosed["diagnosis_id"]
    assert run["review_id"] == review["review_id"]
    assert run["verdict"] == "accepted"
    assert run["verification_result"] == "verified"
    assert run["resolved_rule_ids"] == ["R004", "R005", "R006"]
    assert run["new_rule_ids"] == []
    assert run["remaining_rule_ids"] == []
    assert run["findings_before"] and run["findings_after"] == []

    stored = client.get(f"/api/diagnoses/{diagnosed['diagnosis_id']}").json()
    assert stored["applied"] is True
    assert stored["status"] == "accepted"


def test_an_edited_diagnosis_may_be_applied(client, diagnosed):
    review = client.post(
        "/api/reviews",
        json={
            "diagnosis_id": diagnosed["diagnosis_id"],
            "verdict": "edited",
            "reason_code": "narrowed_scope",
            "corrected_fix_steps": ["vlan 30", "name VLAN30"],
            "corrected_rule_ids": ["R005"],
        },
    ).json()

    run = client.post("/api/fixes/apply", json={"review_id": review["review_id"]}).json()
    assert run["verdict"] == "edited"
    # Reviewer edits win: only the narrowed finding's mutation was proposed.
    assert {mutation["rule_id"] for mutation in run["mutations"]} == {"R005"}


def test_the_diagnosis_id_route_reaches_the_same_approval(client, diagnosed):
    review = _accept(client, diagnosed["diagnosis_id"])
    run = client.post(
        "/api/fixes/apply", json={"diagnosis_id": diagnosed["diagnosis_id"]}
    ).json()
    assert run["review_id"] == review["review_id"], "the server resolved the approval itself"


# --- honesty about what actually ran ------------------------------------------------------


def test_every_fix_run_declares_the_simulated_scope(client, diagnosed):
    review = _accept(client, diagnosed["diagnosis_id"])
    run = client.post("/api/fixes/apply", json={"review_id": review["review_id"]}).json()
    assert run["execution_scope"] == EXECUTION_SCOPE == "simulated_lab_model"
    assert run["disclaimer"] == SIMULATION_DISCLAIMER
    assert "not executed on physical hardware" in run["disclaimer"]

    raw = json.dumps(run).lower()
    for false_claim in ("ssh", "telnet", "netmiko", "pushed to", "physical hardware —"):
        assert false_claim not in raw.replace("not executed on physical hardware", "")


def test_a_fix_run_never_mutates_the_stored_case(client, diagnosed):
    """The simulator works on a deep copy. The dataset must be byte-identical after."""
    before = client.get("/api/cases/CASE-001").json()
    review = _accept(client, diagnosed["diagnosis_id"])
    client.post("/api/fixes/apply", json={"review_id": review["review_id"]})

    assert client.get("/api/cases/CASE-001").json() == before
    fresh = case_repo.get_case("CASE-001", use_cache=False)
    assert fresh is not None
    assert before["lab_state"] == fresh.lab_state.model_dump(mode="json")


def test_fix_runs_can_be_listed_and_fetched(client, diagnosed):
    review = _accept(client, diagnosed["diagnosis_id"])
    run = client.post("/api/fixes/apply", json={"review_id": review["review_id"]}).json()

    assert [r["run_id"] for r in client.get("/api/fixes").json()] == [run["run_id"]]
    assert len(client.get("/api/fixes", params={"case_id": "CASE-001"}).json()) == 1
    assert client.get("/api/fixes", params={"case_id": "CASE-777"}).json() == []
    by_diagnosis = client.get(
        "/api/fixes", params={"diagnosis_id": diagnosed["diagnosis_id"]}
    ).json()
    assert len(by_diagnosis) == 1

    assert client.get(f"/api/fixes/{run['run_id']}").json() == run
    assert client.get("/api/fixes/FIX-000000000000").status_code == 404


def test_fix_runs_can_be_filtered_by_review_id(client, diagnosed):
    """The Fix & Verify page asks by review id, so the server must answer by review id."""
    review = _accept(client, diagnosed["diagnosis_id"])
    run = client.post("/api/fixes/apply", json={"review_id": review["review_id"]}).json()

    by_review = client.get("/api/fixes", params={"review_id": review["review_id"]}).json()
    assert [r["run_id"] for r in by_review] == [run["run_id"]]
    assert len(by_review) == 1, "a review may be applied once, so it selects one run"

    # An unknown review is an empty list, not an error: the page is asking whether a run
    # exists yet, and 'not yet' is a normal answer.
    assert client.get("/api/fixes", params={"review_id": "REV-000000000000"}).json() == []

    # The filters compose, and are case-insensitive like the others.
    both = client.get(
        "/api/fixes",
        params={"review_id": review["review_id"], "diagnosis_id": diagnosed["diagnosis_id"]},
    ).json()
    assert [r["run_id"] for r in both] == [run["run_id"]]
    assert (
        client.get(
            "/api/fixes",
            params={"review_id": review["review_id"], "case_id": "CASE-777"},
        ).json()
        == []
    )
    lowered = client.get(
        "/api/fixes", params={"review_id": review["review_id"].lower()}
    ).json()
    assert [r["run_id"] for r in lowered] == [run["run_id"]]

    # And the older callers are untouched.
    assert len(client.get("/api/fixes").json()) == 1


def test_the_full_demo_flow_in_order(client):
    """Broken case → diagnosis → refusal → human review → fix → verification."""
    case = client.get("/api/cases/CASE-001").json()
    assert case["expected_rule_ids"]

    diagnosis = client.post(
        "/api/diagnose", json={"case_id": "CASE-001", "provider": "mock"}
    ).json()
    assert diagnosis["status"] == "awaiting_human_review" and diagnosis["applied"] is False

    refused = client.post("/api/fixes/apply", json={"diagnosis_id": diagnosis["diagnosis_id"]})
    assert refused.status_code == 409

    review = _accept(client, diagnosis["diagnosis_id"])
    run = client.post("/api/fixes/apply", json={"review_id": review["review_id"]}).json()

    assert run["verification_result"] == "verified"
    assert run["execution_scope"] == "simulated_lab_model"
    assert client.get(f"/api/diagnoses/{diagnosis['diagnosis_id']}").json()["applied"] is True
