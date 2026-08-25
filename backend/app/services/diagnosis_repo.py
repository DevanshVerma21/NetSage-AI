"""Persistence for AI diagnoses.

The bridge between the Phase 2 pipeline (which returns an in-memory
:class:`~backend.app.services.diagnose.DiagnosisResult`) and the Phase 3 store. Every
record it writes is ``awaiting_human_review`` with ``applied=False``; there is no argument,
flag or code path here that can create one in any other state.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Optional

from backend.app.models.records import (
    AWAITING_HUMAN_REVIEW,
    ConfidenceRecord,
    DiagnosisRecord,
    EvidenceIntegrityRecord,
    ReconciliationRecord,
)
from backend.app.services.errors import NotFoundError
from backend.app.services.diagnose import DiagnosisResult
from backend.app.services.record_store import DIAGNOSES_FILE, JsonCollection

collection: JsonCollection[DiagnosisRecord] = JsonCollection(
    DIAGNOSES_FILE, DiagnosisRecord, "diagnosis_id", derived_fields=("rule_ids",)
)


def record_from_result(result: DiagnosisResult) -> DiagnosisRecord:
    """Project a pipeline result into a storable record. No state is decided here."""
    verification = result.evidence_verification
    reconciliation = result.reconciliation
    confidence = result.confidence

    return DiagnosisRecord(
        case_id=result.case_id,
        created_at=result.created_at,
        provider=result.provider,
        model=result.model,
        prompt_name=result.prompt_name,
        prompt_version=result.prompt_version,
        prompt_sha256=result.prompt_sha256,
        rule_findings=list(result.rule_findings),
        ai=result.ai,
        evidence_integrity=EvidenceIntegrityRecord(
            status=verification.status,
            verified_count=verification.verified_count,
            failed_count=verification.failed_count,
            details=verification.details,
            verified_items=[asdict(item) for item in verification.verified_items],
            failed_items=[asdict(item) for item in verification.failed_items],
        ),
        reconciliation=ReconciliationRecord(
            status=reconciliation.status,
            reason=reconciliation.reason,
            matched_rule_ids=list(reconciliation.matched_rule_ids),
            unmatched_rule_ids=list(reconciliation.unmatched_rule_ids),
            rule_categories=list(reconciliation.rule_categories),
            ai_category=reconciliation.ai_category,
        ),
        confidence=ConfidenceRecord(
            model_confidence=confidence.model_confidence,
            effective_confidence=confidence.effective_confidence,
            model_confidence_score=confidence.model_confidence_score,
            effective_confidence_score=confidence.effective_confidence_score,
            was_capped=confidence.was_capped,
            cap_reasons=list(confidence.cap_reasons),
            summary=confidence.summary(),
        ),
        latency_ms=result.latency_ms,
        warnings=list(result.warnings),
        # The human gate, stated explicitly rather than relying on the field defaults.
        status=AWAITING_HUMAN_REVIEW,
        applied=False,
        review_id=None,
    )


def save(result: DiagnosisResult) -> DiagnosisRecord:
    """Persist a pipeline result as a new diagnosis awaiting human review."""
    return collection.append(record_from_result(result))


def all_records(case_id: Optional[str] = None, status: Optional[str] = None) -> list[DiagnosisRecord]:
    records = collection.all()
    if case_id:
        wanted = case_id.strip().lower()
        records = [r for r in records if (r.case_id or "").lower() == wanted]
    if status:
        wanted_status = status.strip().lower()
        records = [r for r in records if r.status.lower() == wanted_status]
    return records


def get(diagnosis_id: str) -> Optional[DiagnosisRecord]:
    return collection.get(diagnosis_id)


def require(diagnosis_id: str) -> DiagnosisRecord:
    record = get(diagnosis_id)
    if record is None:
        raise NotFoundError(f"no diagnosis with id '{diagnosis_id}'")
    return record


def set_review_outcome(diagnosis_id: str, review_id: str, status: str) -> DiagnosisRecord:
    """Record the human verdict on the diagnosis. Never sets ``applied``."""
    record = require(diagnosis_id)
    updated = record.model_copy(update={"status": status, "review_id": review_id})
    return collection.update(updated)


def mark_applied(diagnosis_id: str) -> DiagnosisRecord:
    """Flip ``applied`` to true. The only function that can.

    The record model itself rejects ``applied=True`` unless the diagnosis carries a review
    and an accepted/edited status, so this cannot be used to bypass the gate.
    """
    record = require(diagnosis_id)
    updated = record.model_copy(update={"applied": True})
    DiagnosisRecord.model_validate(updated.model_dump())
    return collection.update(updated)
