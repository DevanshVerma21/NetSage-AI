"""Phase 3 — the read-only API surface: health, the case library, the rule checker.

The rule-check endpoint is the deterministic engine exposed over HTTP. The tests below
assert not only that it works but that it is *not* the AI path: it must produce findings
with no provider configured and no network available.
"""

from __future__ import annotations

from backend.app.models.records import EXECUTION_SCOPE
from backend.app.services import case_repo


def test_health_reports_a_loaded_system(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["cases_loaded"] == len(case_repo.all_cases())
    assert body["rules_registered"] >= 6
    assert body["mandatory_rules"] == ["R001", "R002", "R003", "R004", "R005", "R006"]
    assert body["human_review_required"] is True
    assert body["execution_scope"] == EXECUTION_SCOPE


def test_health_never_exposes_a_credential(client):
    """It reports *whether* a provider is configured, never the key itself."""
    raw = client.get("/api/health").text
    body = client.get("/api/health").json()
    assert isinstance(body["provider_configured"], bool)
    assert "api_key" not in raw.lower()
    assert "AIza" not in raw
    assert "sk-" not in raw


def test_list_cases_returns_summaries(client):
    cases = client.get("/api/cases").json()
    assert len(cases) == len(case_repo.all_cases())
    first = cases[0]
    assert set(first) == {
        "case_id",
        "title",
        "symptom",
        "concept_tag",
        "osi_layer",
        "severity",
        "security_relevant",
        "source_label",
    }
    # Provenance travels with every case: the prototype never claims a hardware capture.
    assert all(case["source_label"] == "simulated-lab" for case in cases)


def test_case_filters_narrow_the_list(client):
    known = case_repo.all_cases()[0]

    by_category = client.get("/api/cases", params={"category": known.concept_tag.value}).json()
    assert known.case_id in [case["case_id"] for case in by_category]

    by_severity = client.get("/api/cases", params={"severity": known.severity.value}).json()
    assert known.case_id in [case["case_id"] for case in by_severity]

    by_layer = client.get("/api/cases", params={"osi_layer": known.osi_layer.value}).json()
    assert known.case_id in [case["case_id"] for case in by_layer]

    assert client.get("/api/cases", params={"category": "NAT_NOT_PRESENT"}).json() == []


def test_case_free_text_search(client):
    known = case_repo.all_cases()[0]
    needle = known.title.split()[0]
    found = client.get("/api/cases", params={"q": needle}).json()
    assert known.case_id in [case["case_id"] for case in found]
    assert client.get("/api/cases", params={"q": "zzzz-no-such-text"}).json() == []


def test_get_case_returns_the_full_record(client):
    body = client.get("/api/cases/CASE-001").json()
    assert body["case_id"] == "CASE-001"
    assert body["show_outputs"], "the evidence the AI must cite from"
    assert body["lab_state"]["devices"]
    assert body["expected_rule_ids"]


def test_unknown_case_is_404(client):
    response = client.get("/api/cases/CASE-999")
    assert response.status_code == 404
    assert "CASE-999" in response.json()["detail"]


def test_rules_check_runs_the_engine_without_the_ai(client):
    response = client.post("/api/rules/check", json={"case_id": "CASE-001"})
    assert response.status_code == 200
    body = response.json()
    assert body["ai_used"] is False
    assert body["rule_ids"] == ["R004", "R005", "R006"]
    assert body["finding_count"] == len(body["findings"])
    assert all(finding["confidence"] == "deterministic" for finding in body["findings"])


def test_rules_check_accepts_an_ad_hoc_lab_state(client):
    from tests.conftest import clean_flows, clean_state

    state = clean_state()
    body = {
        "lab_state": state.model_dump(mode="json"),
        "intended_flows": [flow.model_dump(mode="json") for flow in clean_flows()],
    }
    response = client.post("/api/rules/check", json=body)
    assert response.status_code == 200
    assert response.json()["findings"] == [], "the healthy topology must fire nothing"
    assert response.json()["case_id"] is None


def test_rules_check_can_be_restricted_to_one_rule(client):
    body = client.post("/api/rules/check", json={"case_id": "CASE-001", "only": ["R005"]}).json()
    assert body["rule_ids"] == ["R005"]


def test_rules_check_rejects_a_bad_request(client):
    assert client.post("/api/rules/check", json={}).status_code == 422
    assert client.post("/api/rules/check", json={"case_id": "CASE-404"}).status_code == 404
    unknown = client.post("/api/rules/check", json={"case_id": "CASE-001", "only": ["R099"]})
    assert unknown.status_code == 422


def test_the_api_declares_no_device_connectivity(client):
    """The OpenAPI surface must contain nothing that pushes configuration to a device."""
    paths = client.get("/openapi.json").json()["paths"]
    joined = " ".join(paths).lower()
    for forbidden in ("ssh", "telnet", "netmiko", "exec", "command", "push", "deploy"):
        assert forbidden not in joined
