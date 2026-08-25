"""Confidence capping tests.

Covers every row of the capping table plus the interactions between rows. The central
property under test: the model's confidence is an input, and ``effective_confidence`` is
computed from the independent checks — never simply echoed.
"""

from __future__ import annotations

import pytest

from backend.app.ai.confidence import cap_confidence
from backend.app.ai.evidence_verifier import (
    EvidenceVerificationResult,
    FailedItem,
    VerifiedItem,
)
from backend.app.ai.reconciler import ReconciliationResult
from backend.app.models.diagnosis import AIDiagnosis, Evidence


def make_diagnosis(
    confidence: str = "high",
    score: float = 0.9,
    insufficient: bool = False,
    evidence_count: int = 2,
    category: str = "VLAN",
    osi_layer: str = "L2",
) -> AIDiagnosis:
    return AIDiagnosis(
        root_cause="Test root cause.",
        confidence=confidence,
        confidence_score=score,
        osi_layer=osi_layer,
        category=category,
        evidence=[
            Evidence(
                source_command="show vlan brief",
                excerpt=f"line {i}",
                why_it_matters="test",
            )
            for i in range(evidence_count)
        ],
        insufficient_evidence=insufficient,
        next_command="show vlan brief",
        notes_for_reviewer="test",
    )


def verification(status: str, verified: int = 2, failed: int = 0):
    return EvidenceVerificationResult(
        status=status,
        verified_items=[
            VerifiedItem(
                index=i,
                source_command="show vlan brief",
                excerpt=f"line {i}",
                matched_command="show vlan brief",
            )
            for i in range(verified)
        ],
        failed_items=[
            FailedItem(
                index=100 + i,
                source_command="show vlan brief",
                excerpt="fabricated",
                reason="excerpt_not_found",
                detail="test",
            )
            for i in range(failed)
        ],
    )


def reconciliation(status: str):
    return ReconciliationResult(status=status, reason="test")


# --- G. evidence failure caps to LOW --------------------------------------------------


def test_evidence_failure_caps_to_low():
    decision = cap_confidence(
        make_diagnosis(confidence="high", score=0.92),
        verification("failed", verified=0, failed=3),
        reconciliation("agree"),
    )

    assert decision.model_confidence == "high"
    assert decision.effective_confidence == "low"
    assert decision.was_capped is True


def test_both_confidences_are_preserved_separately():
    """The reviewer must be able to see what the AI claimed *and* what survived checking."""
    decision = cap_confidence(
        make_diagnosis(confidence="high", score=0.92),
        verification("failed", verified=0, failed=1),
        reconciliation("agree"),
    )

    assert decision.model_confidence == "high"
    assert decision.model_confidence_score == 0.92
    assert decision.effective_confidence == "low"
    assert decision.effective_confidence_score <= 0.4


def test_evidence_failure_beats_every_other_cap():
    """LOW is the lowest ceiling, so it wins regardless of what else applies."""
    decision = cap_confidence(
        make_diagnosis(confidence="high", insufficient=True),
        verification("failed", verified=0, failed=2),
        reconciliation("conflict"),
    )

    assert decision.effective_confidence == "low"


# --- H. conflict caps to MEDIUM -------------------------------------------------------


def test_conflict_caps_to_medium():
    decision = cap_confidence(
        make_diagnosis(confidence="high", score=0.9),
        verification("passed", verified=3),
        reconciliation("conflict"),
    )

    assert decision.model_confidence == "high"
    assert decision.effective_confidence == "medium"


# --- I. insufficient_evidence caps to MEDIUM ------------------------------------------


def test_insufficient_evidence_caps_to_medium():
    decision = cap_confidence(
        make_diagnosis(confidence="high", insufficient=True, evidence_count=2),
        verification("passed", verified=2),
        reconciliation("agree"),
    )

    assert decision.effective_confidence == "medium"


# --- J. ai_only caps to MEDIUM --------------------------------------------------------


def test_ai_only_caps_to_medium():
    decision = cap_confidence(
        make_diagnosis(confidence="high"),
        verification("passed", verified=3),
        reconciliation("ai_only"),
    )

    assert decision.effective_confidence == "medium"


# --- K / L. the two-citation rule for HIGH --------------------------------------------


def test_high_with_one_verified_citation_caps_to_medium():
    decision = cap_confidence(
        make_diagnosis(confidence="high", evidence_count=1),
        verification("passed", verified=1),
        reconciliation("agree"),
    )

    assert decision.effective_confidence == "medium"
    assert any("at least 2" in reason for reason in decision.cap_reasons)


def test_high_with_zero_verified_citations_caps_to_medium_or_lower():
    decision = cap_confidence(
        make_diagnosis(confidence="high", insufficient=True, evidence_count=0),
        verification("passed", verified=0),
        reconciliation("agree"),
    )

    assert decision.effective_confidence in {"low", "medium"}


def test_high_with_two_verified_citations_stays_high():
    """The one path on which HIGH survives: corroborated, agreeing, and sufficient."""
    decision = cap_confidence(
        make_diagnosis(confidence="high", score=0.88, evidence_count=2),
        verification("passed", verified=2),
        reconciliation("agree"),
    )

    assert decision.effective_confidence == "high"
    assert decision.was_capped is False
    # Uncapped, so the model's own score is preserved exactly.
    assert decision.effective_confidence_score == 0.88


def test_high_with_many_verified_citations_stays_high():
    decision = cap_confidence(
        make_diagnosis(confidence="high", score=0.95, evidence_count=4),
        verification("passed", verified=4),
        reconciliation("agree"),
    )

    assert decision.effective_confidence == "high"


# --- preservation and non-inflation ---------------------------------------------------


def test_uncapped_medium_is_preserved():
    decision = cap_confidence(
        make_diagnosis(confidence="medium", score=0.6),
        verification("passed", verified=2),
        reconciliation("agree"),
    )

    assert decision.effective_confidence == "medium"
    assert decision.was_capped is False
    assert decision.effective_confidence_score == 0.6


def test_capping_never_raises_confidence():
    """A LOW diagnosis must never be promoted, whatever the checks say."""
    decision = cap_confidence(
        make_diagnosis(confidence="low", score=0.2),
        verification("passed", verified=5),
        reconciliation("agree"),
    )

    assert decision.effective_confidence == "low"
    assert decision.effective_confidence_score == 0.2


def test_capping_never_raises_the_numeric_score():
    decision = cap_confidence(
        make_diagnosis(confidence="medium", score=0.45),
        verification("passed", verified=2),
        reconciliation("agree"),
    )

    assert decision.effective_confidence_score <= 0.45


def test_partial_evidence_alone_does_not_cap():
    """Partial verification is surfaced as a warning, but it is not in the capping table."""
    decision = cap_confidence(
        make_diagnosis(confidence="high", evidence_count=3),
        verification("partial", verified=2, failed=1),
        reconciliation("agree"),
    )

    assert decision.effective_confidence == "high"


def test_rules_only_does_not_cap_on_its_own():
    """rules_only is not a capping condition; it is a reconciliation signal."""
    decision = cap_confidence(
        make_diagnosis(confidence="medium", insufficient=False),
        verification("passed", verified=2),
        reconciliation("rules_only"),
    )

    assert decision.effective_confidence == "medium"


# --- composition ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "evidence_status,recon_status,insufficient,verified,expected",
    [
        ("failed", "agree", False, 0, "low"),
        ("failed", "conflict", True, 0, "low"),
        ("passed", "conflict", False, 3, "medium"),
        ("passed", "ai_only", False, 3, "medium"),
        ("passed", "agree", True, 3, "medium"),
        ("passed", "agree", False, 1, "medium"),
        ("passed", "agree", False, 2, "high"),
        ("partial", "agree", False, 2, "high"),
    ],
)
def test_capping_table(evidence_status, recon_status, insufficient, verified, expected):
    """The specified table, exercised row by row."""
    decision = cap_confidence(
        make_diagnosis(confidence="high", insufficient=insufficient),
        verification(evidence_status, verified=verified, failed=1 if evidence_status != "passed" else 0),
        reconciliation(recon_status),
    )

    assert decision.effective_confidence == expected


def test_lowest_ceiling_wins_when_several_apply():
    decision = cap_confidence(
        make_diagnosis(confidence="high", evidence_count=1),
        verification("failed", verified=0, failed=1),
        reconciliation("ai_only"),
    )

    assert decision.effective_confidence == "low"


def test_cap_reasons_are_reported_only_when_binding():
    """A diagnosis that was not capped must not display cap reasoning."""
    decision = cap_confidence(
        make_diagnosis(confidence="medium", score=0.6),
        verification("passed", verified=2),
        reconciliation("agree"),
    )

    assert decision.applied_caps == []
    assert "reduced" not in decision.summary()


def test_summary_explains_a_cap():
    decision = cap_confidence(
        make_diagnosis(confidence="high", score=0.9),
        verification("failed", verified=0, failed=2),
        reconciliation("agree"),
    )

    summary = decision.summary()
    assert "HIGH" in summary and "LOW" in summary
    assert "because" in summary
