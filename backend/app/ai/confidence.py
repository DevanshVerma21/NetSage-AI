"""Deterministic confidence capping.

The model's confidence is an **input**, never the output. This module computes an
``effective_confidence`` from the model's claim plus what the independent checks actually
found, and keeps ``model_confidence`` alongside it so a reviewer can always see the
difference between what the AI claimed and what the system was willing to stand behind.

The capping table is the one specified for this phase:

    ================================================  ==================
    Condition                                          Maximum confidence
    ================================================  ==================
    evidence verification FAILED                       LOW
    AI / rule conflict                                 MEDIUM
    insufficient_evidence = true                       MEDIUM
    ai_only                                            MEDIUM
    HIGH claimed with fewer than 2 verified citations   MEDIUM
    otherwise                                          (model's value preserved)
    ================================================  ==================

Caps compose: when several apply, the lowest ceiling wins.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.app.ai.evidence_verifier import EvidenceVerificationResult
from backend.app.ai.reconciler import ReconciliationResult
from backend.app.models.diagnosis import CONFIDENCE_RANK, AIDiagnosis, ConfidenceLiteral

MIN_EVIDENCE_FOR_HIGH = 2


@dataclass
class AppliedCap:
    """One ceiling that was applied, and why."""

    condition: str
    ceiling: ConfidenceLiteral
    explanation: str


@dataclass
class ConfidenceDecision:
    model_confidence: ConfidenceLiteral
    """What the AI claimed. Preserved verbatim, never overwritten."""
    effective_confidence: ConfidenceLiteral
    """What the system is willing to stand behind after independent checks."""
    model_confidence_score: float
    effective_confidence_score: float
    applied_caps: list[AppliedCap] = field(default_factory=list)

    @property
    def was_capped(self) -> bool:
        return self.effective_confidence != self.model_confidence

    @property
    def cap_reasons(self) -> list[str]:
        return [cap.explanation for cap in self.applied_caps]

    def summary(self) -> str:
        if not self.was_capped:
            return (
                f"Confidence {self.effective_confidence.upper()} "
                f"({self.effective_confidence_score:.2f}) — the model's own confidence, "
                "which the independent checks did not require reducing."
            )
        conditions = "; ".join(cap.condition for cap in self.applied_caps)
        return (
            f"Confidence reduced from {self.model_confidence.upper()} "
            f"({self.model_confidence_score:.2f}) to "
            f"{self.effective_confidence.upper()} "
            f"({self.effective_confidence_score:.2f}) because: {conditions}."
        )


# Representative score for a capped band. Only used when the model's own score sits above
# the ceiling; a score already inside the band is left alone.
_BAND_SCORE: dict[str, float] = {"low": 0.2, "medium": 0.55, "high": 0.85}


def cap_confidence(
    diagnosis: AIDiagnosis,
    verification: EvidenceVerificationResult,
    reconciliation: ReconciliationResult,
) -> ConfidenceDecision:
    """Apply every applicable ceiling and return both confidences."""
    model_confidence: ConfidenceLiteral = diagnosis.confidence
    caps: list[AppliedCap] = []

    if verification.status == "failed":
        caps.append(
            AppliedCap(
                condition="evidence verification failed",
                ceiling="low",
                explanation=(
                    "Evidence verification FAILED: none of the AI's citations could be "
                    "located in the supplied show-command output, so nothing it claims is "
                    "substantiated. Capped at LOW."
                ),
            )
        )

    if reconciliation.status == "conflict":
        caps.append(
            AppliedCap(
                condition="AI diagnosis conflicts with the deterministic findings",
                ceiling="medium",
                explanation=(
                    "The AI's diagnosis contradicts what the rule engine observed in the "
                    "actual configuration. Capped at MEDIUM pending reviewer adjudication."
                ),
            )
        )

    if diagnosis.insufficient_evidence:
        caps.append(
            AppliedCap(
                condition="the model reported insufficient evidence",
                ceiling="medium",
                explanation=(
                    "The model itself reported that the evidence is insufficient to "
                    "establish a root cause, so no high-confidence conclusion is available. "
                    "Capped at MEDIUM."
                ),
            )
        )

    if reconciliation.status == "ai_only":
        caps.append(
            AppliedCap(
                condition="no deterministic finding corroborates the diagnosis",
                ceiling="medium",
                explanation=(
                    "The deterministic checker found nothing, so this diagnosis is "
                    "uncorroborated. Capped at MEDIUM."
                ),
            )
        )

    if (
        model_confidence == "high"
        and verification.verified_count < MIN_EVIDENCE_FOR_HIGH
    ):
        caps.append(
            AppliedCap(
                condition=(
                    f"HIGH confidence claimed with only {verification.verified_count} "
                    f"verified citation(s)"
                ),
                ceiling="medium",
                explanation=(
                    f"HIGH confidence requires at least {MIN_EVIDENCE_FOR_HIGH} "
                    f"independently verified citations; only {verification.verified_count} "
                    "verified. Capped at MEDIUM."
                ),
            )
        )

    effective = model_confidence
    for cap in caps:
        if CONFIDENCE_RANK[cap.ceiling] < CONFIDENCE_RANK[effective]:
            effective = cap.ceiling

    # Keep only the caps that actually bound the result, so the reviewer is not shown
    # ceilings that were never reached.
    binding = [
        cap for cap in caps if CONFIDENCE_RANK[cap.ceiling] <= CONFIDENCE_RANK[effective]
    ]

    return ConfidenceDecision(
        model_confidence=model_confidence,
        effective_confidence=effective,
        model_confidence_score=diagnosis.confidence_score,
        effective_confidence_score=_effective_score(
            diagnosis.confidence_score, model_confidence, effective
        ),
        applied_caps=binding if effective != model_confidence else [],
    )


def _effective_score(
    model_score: float, model_confidence: ConfidenceLiteral, effective: ConfidenceLiteral
) -> float:
    """Clamp the numeric score into the effective band, without ever inflating it.

    When no cap applied, the model's own score is preserved exactly — the table says an
    uncapped confidence keeps the model's validated value, and silently nudging 0.60 to 0.55
    would misreport what the model actually claimed.
    """
    if effective == model_confidence:
        return model_score
    ceiling = _BAND_SCORE[effective]
    return round(min(model_score, ceiling), 2)
