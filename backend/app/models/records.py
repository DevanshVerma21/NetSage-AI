"""Persisted records: diagnoses, human reviews, and simulated fix runs.

These are the Phase 3 storage shapes. They are deliberately separate from the Phase 2
in-memory :class:`~backend.app.services.diagnose.DiagnosisResult`: that object carries
dataclasses tuned for the pipeline, while these are flat, JSON-stable, Pydantic-validated
records that survive a restart and can be served straight to the API.

Three invariants are enforced here rather than left to the API layer:

* a new :class:`DiagnosisRecord` is always ``awaiting_human_review`` with ``applied=False``
* ``applied`` can only be set through :meth:`DiagnosisRecord.mark_applied`
* every :class:`FixRunRecord` carries ``execution_scope="simulated_lab_model"`` and the
  simulation disclaimer, because a fix run that does not say what it actually ran against
  is the single most misleading record this system could store.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.models.diagnosis import (
    AIDiagnosis,
    ConfidenceLiteral,
    IntegrityLiteral,
    ReconciliationLiteral,
)
from backend.app.rules.engine import Finding

# --- vocabulary --------------------------------------------------------------------------

DiagnosisStatusLiteral = Literal[
    "awaiting_human_review",  # the only state a new diagnosis may be created in
    "accepted",
    "edited",
    "rejected",
]
ReviewVerdictLiteral = Literal["accepted", "edited", "rejected"]
VerificationResultLiteral = Literal["verified", "partial", "failed"]

AWAITING_HUMAN_REVIEW = "awaiting_human_review"

EXECUTION_SCOPE = "simulated_lab_model"
"""The only execution scope this system has. There is no other code path."""

SIMULATION_DISCLAIMER = (
    "Verified against simulated lab model — not executed on physical hardware or "
    "Packet Tracer."
)

VERDICT_TO_STATUS: dict[str, str] = {
    "accepted": "accepted",
    "edited": "edited",
    "rejected": "rejected",
}

APPLICABLE_VERDICTS = ("accepted", "edited")
"""Verdicts that permit a simulated fix. ``rejected`` is absent by design."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


# --- diagnoses ---------------------------------------------------------------------------


class EvidenceIntegrityRecord(BaseModel):
    """The evidence verifier's verdict, stored in full.

    Failed citations are kept, not dropped: a reviewer needs to see exactly what the model
    claimed that could not be found in the supplied output.
    """

    model_config = ConfigDict(extra="forbid")

    status: IntegrityLiteral
    verified_count: int = 0
    failed_count: int = 0
    details: str = ""
    verified_items: list[dict] = Field(default_factory=list)
    failed_items: list[dict] = Field(default_factory=list)


class ReconciliationRecord(BaseModel):
    """How the AI's diagnosis compared with the deterministic findings."""

    model_config = ConfigDict(extra="forbid")

    status: ReconciliationLiteral
    reason: str = ""
    matched_rule_ids: list[str] = Field(default_factory=list)
    unmatched_rule_ids: list[str] = Field(default_factory=list)
    rule_categories: list[str] = Field(default_factory=list)
    ai_category: str = ""


class ConfidenceRecord(BaseModel):
    """The model's confidence and the system's, kept separate on purpose."""

    model_config = ConfigDict(extra="forbid")

    model_confidence: ConfidenceLiteral
    effective_confidence: ConfidenceLiteral
    model_confidence_score: float
    effective_confidence_score: float
    was_capped: bool = False
    cap_reasons: list[str] = Field(default_factory=list)
    summary: str = ""


class DiagnosisRecord(BaseModel):
    """One stored AI proposal, with every independent check that was run on it."""

    model_config = ConfigDict(extra="forbid")

    diagnosis_id: str = Field(default_factory=lambda: _new_id("DIAG"))
    case_id: Optional[str] = None
    created_at: str = Field(default_factory=_now)

    # --- provenance: which model, which prompt, which exact prompt bytes ---------------
    provider: str
    model: str
    prompt_name: str
    prompt_version: str
    prompt_sha256: str

    # --- the deterministic half --------------------------------------------------------
    rule_findings: list[Finding] = Field(default_factory=list)

    # --- the AI half -------------------------------------------------------------------
    ai: AIDiagnosis

    # --- the independent checks --------------------------------------------------------
    evidence_integrity: EvidenceIntegrityRecord
    reconciliation: ReconciliationRecord
    confidence: ConfidenceRecord

    # --- metadata ----------------------------------------------------------------------
    latency_ms: int = 0
    warnings: list[str] = Field(default_factory=list)

    # --- the human gate ----------------------------------------------------------------
    status: DiagnosisStatusLiteral = AWAITING_HUMAN_REVIEW
    applied: bool = False
    review_id: Optional[str] = None

    @model_validator(mode="after")
    def _applied_requires_a_review(self) -> "DiagnosisRecord":
        """``applied`` without a review would mean the gate was bypassed somewhere."""
        if self.applied and self.review_id is None:
            raise ValueError("a diagnosis cannot be applied without a review_id")
        if self.applied and self.status not in ("accepted", "edited"):
            raise ValueError(f"a '{self.status}' diagnosis cannot be applied")
        return self

    # --- convenience -------------------------------------------------------------------

    @property
    def model_confidence(self) -> str:
        return self.confidence.model_confidence

    @property
    def effective_confidence(self) -> str:
        return self.confidence.effective_confidence

    @property
    def rule_ids(self) -> list[str]:
        return sorted({finding.rule_id for finding in self.rule_findings})

    def mutations(self, only_rule_ids: Optional[list[str]] = None) -> list[dict]:
        """Typed LabState mutations proposed by the deterministic findings.

        This is the *only* source of fix mutations. A client cannot supply them, so a
        client cannot ask the simulator to make an arbitrary change.
        """
        wanted = {rid.upper() for rid in only_rule_ids} if only_rule_ids else None
        out: list[dict] = []
        for finding in self.rule_findings:
            if finding.suggested_mutation is None:
                continue
            if wanted is not None and finding.rule_id.upper() not in wanted:
                continue
            mutation = dict(finding.suggested_mutation)
            mutation.setdefault("_rule_id", finding.rule_id)
            if mutation not in out:
                out.append(mutation)
        return out


# --- reviews -----------------------------------------------------------------------------


class AgreementRecord(BaseModel):
    """Whether the human agreed with the AI, field by field.

    Required by the document's Responsible-AI log and by the dashboard's AI-vs-human
    agreement metric, which must be computed from these records rather than hard-coded.
    """

    model_config = ConfigDict(extra="forbid")

    root_cause: bool
    osi_layer: bool
    category: bool

    @property
    def fully_agreed(self) -> bool:
        return self.root_cause and self.osi_layer and self.category

    @property
    def disagreed_fields(self) -> list[str]:
        return [
            name
            for name, agreed in (
                ("root_cause", self.root_cause),
                ("osi_layer", self.osi_layer),
                ("category", self.category),
            )
            if not agreed
        ]


class ReviewRecord(BaseModel):
    """A human verdict on one diagnosis. Exactly one review per diagnosis."""

    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(default_factory=lambda: _new_id("REV"))
    diagnosis_id: str
    case_id: Optional[str] = None
    created_at: str = Field(default_factory=_now)

    verdict: ReviewVerdictLiteral
    reviewer: str = "human-reviewer"
    reason_code: Optional[str] = None
    notes: Optional[str] = None

    # --- what the human actually concluded, when it differs from the AI ---------------
    corrected_root_cause: Optional[str] = None
    corrected_osi_layer: Optional[str] = None
    corrected_category: Optional[str] = None
    corrected_rule_ids: list[str] = Field(default_factory=list)
    """Optional: restrict the simulated fix to these findings. Empty means all of them."""
    corrected_fix_steps: list[str] = Field(default_factory=list)

    agreement: AgreementRecord

    @property
    def permits_fix(self) -> bool:
        return self.verdict in APPLICABLE_VERDICTS

    @property
    def final_root_cause(self) -> Optional[str]:
        """The reviewer's wording where they supplied one. Reviewer edits win."""
        return self.corrected_root_cause


# --- fix runs ----------------------------------------------------------------------------


class AppliedMutation(BaseModel):
    """One mutation the simulator applied to its copy of the lab state — or declined to."""

    model_config = ConfigDict(extra="forbid")

    type: str
    rule_id: Optional[str] = None
    target: str = ""
    detail: str = ""
    applied: bool = True
    skipped_reason: Optional[str] = None


class FixRunRecord(BaseModel):
    """A simulated fix and its deterministic before/after verification.

    Nothing in this record describes a real device. ``execution_scope`` is fixed at
    ``simulated_lab_model`` and validated, so no future caller can quietly widen it.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(default_factory=lambda: _new_id("FIX"))
    diagnosis_id: str
    review_id: str
    case_id: Optional[str] = None
    created_at: str = Field(default_factory=_now)

    verdict: ReviewVerdictLiteral

    mutations: list[AppliedMutation] = Field(default_factory=list)
    findings_before: list[Finding] = Field(default_factory=list)
    findings_after: list[Finding] = Field(default_factory=list)
    resolved_rule_ids: list[str] = Field(default_factory=list)
    new_rule_ids: list[str] = Field(default_factory=list)
    remaining_rule_ids: list[str] = Field(default_factory=list)
    verification_result: VerificationResultLiteral
    verification_summary: str = ""

    execution_scope: Literal["simulated_lab_model"] = EXECUTION_SCOPE
    disclaimer: str = SIMULATION_DISCLAIMER

    @model_validator(mode="after")
    def _disclaimer_is_intact(self) -> "FixRunRecord":
        if self.disclaimer != SIMULATION_DISCLAIMER:
            raise ValueError("the simulation disclaimer must be stored verbatim")
        return self
