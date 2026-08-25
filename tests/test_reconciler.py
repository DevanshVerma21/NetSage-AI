"""Reconciler tests — all five states, plus the boundaries between them."""

from __future__ import annotations

from backend.app.ai.reconciler import reconcile
from backend.app.models.enums import ConceptTag, OSILayer, Severity
from backend.app.rules.engine import Finding, RuleEvidence
from backend.app.models.diagnosis import AIDiagnosis, Evidence


def make_diagnosis(
    category: str = "VLAN",
    osi_layer: str = "L2",
    insufficient: bool = False,
) -> AIDiagnosis:
    return AIDiagnosis(
        root_cause="Test root cause.",
        confidence="medium",
        confidence_score=0.6,
        osi_layer=osi_layer,
        category=category,
        evidence=[
            Evidence(
                source_command="show vlan brief",
                excerpt="30   SERVERS",
                why_it_matters="test",
            )
        ],
        insufficient_evidence=insufficient,
        next_command="show vlan brief",
        notes_for_reviewer="test",
    )


def make_finding(
    rule_id: str = "R005",
    category: ConceptTag = ConceptTag.VLAN,
    osi_layer: OSILayer = OSILayer.L2,
    severity: Severity = Severity.HIGH,
) -> Finding:
    return Finding(
        rule_id=rule_id,
        rule_name=f"Test rule {rule_id}",
        category=category,
        severity=severity,
        osi_layer=osi_layer,
        message="test finding",
        evidence=[RuleEvidence(source="test", detail="test")],
    )


# --- M. all five states ---------------------------------------------------------------


def test_agree_when_category_matches_the_findings():
    result = reconcile(make_diagnosis(category="VLAN"), [make_finding("R005", ConceptTag.VLAN)])

    assert result.status == "agree"
    assert result.matched_rule_ids == ["R005"]
    assert result.warning() is None


def test_agree_when_ai_covers_the_primary_family_among_several():
    """A compound fault produces findings in several categories; matching the primary one
    is still agreement, with the others noted as likely consequences."""
    findings = [
        make_finding("R005", ConceptTag.VLAN),
        make_finding("R004", ConceptTag.INTERFACE_CONFIG, OSILayer.L1),
        make_finding("R006", ConceptTag.ROUTING, OSILayer.L3),
    ]

    result = reconcile(make_diagnosis(category="VLAN"), findings)

    assert result.status == "agree"
    assert result.matched_rule_ids == ["R005"]
    assert result.unmatched_rule_ids == ["R004", "R006"]
    assert "consequences" in result.reason


def test_partial_when_category_differs_but_osi_layer_matches():
    """Right part of the stack, wrong fault family."""
    result = reconcile(
        make_diagnosis(category="ROUTING", osi_layer="L3"),
        [make_finding("R003", ConceptTag.GATEWAY, OSILayer.L3)],
    )

    assert result.status == "partial"
    assert "same part of the stack" in result.reason
    assert "PARTIAL AGREEMENT" in result.warning()


def test_ai_only_when_no_rule_fired():
    result = reconcile(make_diagnosis(category="DNS"), [])

    assert result.status == "ai_only"
    assert "found nothing" in result.reason
    assert "AI-ONLY" in result.warning()


def test_rules_only_when_ai_declines_but_rules_fired():
    result = reconcile(
        make_diagnosis(insufficient=True),
        [make_finding("R005", ConceptTag.VLAN)],
    )

    assert result.status == "rules_only"
    assert result.unmatched_rule_ids == ["R005"]
    assert "RULES-ONLY" in result.warning()


def test_conflict_when_neither_category_nor_layer_matches():
    result = reconcile(
        make_diagnosis(category="DNS", osi_layer="L7"),
        [make_finding("R004", ConceptTag.INTERFACE_CONFIG, OSILayer.L1)],
    )

    assert result.status == "conflict"
    assert result.is_conflict is True
    assert "CONFLICT" in result.warning()


# --- boundaries -----------------------------------------------------------------------


def test_no_findings_and_ai_declines_is_agreement():
    """Both concluded nothing is determinable, which is genuine agreement."""
    result = reconcile(make_diagnosis(insufficient=True), [])

    assert result.status == "agree"
    assert "same conclusion" in result.reason


def test_conflict_records_what_each_side_said():
    """A reviewer adjudicating a conflict needs both positions stated."""
    result = reconcile(
        make_diagnosis(category="NAT", osi_layer="L4"),
        [
            make_finding("R005", ConceptTag.VLAN, OSILayer.L2),
            make_finding("R006", ConceptTag.ROUTING, OSILayer.L3),
        ],
    )

    assert result.status == "conflict"
    assert result.ai_category == "NAT"
    assert result.rule_categories == ["ROUTING", "VLAN"]
    assert result.unmatched_rule_ids == ["R005", "R006"]


def test_every_state_is_reachable_and_distinct():
    """Guards against a refactor collapsing two states into one."""
    vlan_finding = [make_finding("R005", ConceptTag.VLAN, OSILayer.L2)]

    states = {
        reconcile(make_diagnosis(category="VLAN"), vlan_finding).status,
        reconcile(
            make_diagnosis(category="ROUTING", osi_layer="L2"), vlan_finding
        ).status,
        reconcile(make_diagnosis(category="DNS"), []).status,
        reconcile(make_diagnosis(insufficient=True), vlan_finding).status,
        reconcile(make_diagnosis(category="DNS", osi_layer="L7"), vlan_finding).status,
    }

    assert states == {"agree", "partial", "ai_only", "rules_only", "conflict"}


def test_reconciliation_is_deterministic():
    diagnosis = make_diagnosis(category="VLAN")
    findings = [
        make_finding("R005", ConceptTag.VLAN),
        make_finding("R006", ConceptTag.ROUTING, OSILayer.L3),
    ]

    first = reconcile(diagnosis, findings)
    second = reconcile(diagnosis, findings)

    assert first.status == second.status
    assert first.reason == second.reason
    assert first.matched_rule_ids == second.matched_rule_ids


def test_reconciler_uses_no_language_model(monkeypatch):
    """Reconciliation must be pure computation — never a second model call."""
    import backend.app.ai.reconciler as module

    assert not hasattr(module, "build_provider")
    source = module.__doc__ or ""
    assert "No language model is involved" in source
