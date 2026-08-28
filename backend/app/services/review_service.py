"""The human review gate.

This module is the gate. Everything about "did a human look at this, and what did they
decide" is decided here, server-side, from stored records — never from anything the client
asserts about its own state.

The three verdicts carry different evidentiary burdens, and they are enforced rather than
documented:

* **accepted** — the reviewer agrees. A reason code is optional.
* **edited** — the reviewer partly disagrees, so they must say why (``reason_code``) and
  what the corrected conclusion is. An "edit" that records no correction is not a review.
* **rejected** — the reviewer disagrees. They must supply both a reason code and notes,
  because a rejection is the most valuable record in the Responsible-AI log and a bare
  "rejected" teaches nobody anything.

Exactly one review per diagnosis. A second attempt is a conflict, not an overwrite: the
audit trail of who decided what, when, is the point of the record.
"""

from __future__ import annotations

from typing import Optional

from backend.app.models.enums import ConceptTag, OSILayer
from backend.app.models.records import (
    VERDICT_TO_STATUS,
    AgreementRecord,
    DiagnosisRecord,
    ReviewRecord,
)
from backend.app.services import case_repo, diagnosis_repo
from backend.app.services.errors import ConflictError, NotFoundError, ValidationError
from backend.app.services.record_store import REVIEWS_FILE, JsonCollection

collection: JsonCollection[ReviewRecord] = JsonCollection(
    REVIEWS_FILE, ReviewRecord, "review_id"
)

VALID_VERDICTS = ("accepted", "edited", "rejected")

#: Verdicts that represent a human disagreeing with the model, rather than agreeing with it.
CORRECTION_VERDICTS = ("edited", "rejected")

#: Providers whose output is generated locally rather than by a model call. A human may review
#: such a diagnosis — the gate applies to every diagnosis without exception — but correcting a
#: fixture is not evidence about model behaviour, so it must never count toward the
#: Responsible-AI correction requirement.
SYNTHETIC_PROVIDERS = ("mock",)
GENUINE_PROVIDERS = ("gemini", "anthropic")


def is_genuine_model_diagnosis(diagnosis: Optional[DiagnosisRecord]) -> bool:
    """True only when this diagnosis came from an actual provider call.

    A missing diagnosis record fails as well: a correction that cannot be traced back to a
    stored model output is not evidence about a model either.
    """
    if diagnosis is None:
        return False
    return (diagnosis.provider or "").lower() in GENUINE_PROVIDERS


def review_candidates() -> list[dict]:
    """Return stored, unreviewed model diagnoses with their case ground truth."""
    candidates = []
    for diagnosis in diagnosis_repo.all_records(status="awaiting_human_review"):
        if not is_genuine_model_diagnosis(diagnosis):
            continue
        case = case_repo.get_case(diagnosis.case_id or "")
        if case is None:
            continue
        candidates.append(
            {
                "case_id": case.case_id,
                "diagnosis_id": diagnosis.diagnosis_id,
                "provider": diagnosis.provider,
                "model": diagnosis.model,
                "prompt_version": diagnosis.prompt_version,
                "root_cause": diagnosis.ai.root_cause,
                "category": diagnosis.ai.category,
                "osi_layer": diagnosis.ai.osi_layer,
                "confidence": diagnosis.ai.confidence,
                "effective_confidence": diagnosis.effective_confidence,
                "evidence_integrity": diagnosis.evidence_integrity.status,
                "reconciliation": diagnosis.reconciliation.status,
                "rule_findings": [finding.model_dump(mode="json") for finding in diagnosis.rule_findings],
                "evidence": [item.model_dump(mode="json") for item in diagnosis.ai.evidence],
                "fix_steps": [step.model_dump(mode="json") for step in diagnosis.ai.fix_steps],
                "symptom": case.symptom,
                "expected_fault": case.expected_fault,
                "expected_category": case.concept_tag.value,
                "expected_osi_layer": case.osi_layer.value,
                "expected_rule_ids": list(case.expected_rule_ids),
            }
        )
    return sorted(candidates, key=lambda item: (item["case_id"], item["diagnosis_id"]))


def genuine_corrections(reviews: Optional[list[ReviewRecord]] = None) -> list[ReviewRecord]:
    """The reviews that count toward the Responsible-AI requirement.

    One definition, used by both the dashboard and the log builder, so the headline figure and
    the file that backs it can never disagree.
    """
    records = all_records() if reviews is None else reviews
    return [
        review
        for review in records
        if review.verdict in CORRECTION_VERDICTS
        and is_genuine_model_diagnosis(diagnosis_repo.get(review.diagnosis_id))
    ]


def synthetic_corrections(reviews: Optional[list[ReviewRecord]] = None) -> list[ReviewRecord]:
    """Correction-shaped reviews that do not count, reported rather than dropped in silence."""
    records = all_records() if reviews is None else reviews
    return [
        review
        for review in records
        if review.verdict in CORRECTION_VERDICTS
        and not is_genuine_model_diagnosis(diagnosis_repo.get(review.diagnosis_id))
    ]


# --- lookups ------------------------------------------------------------------------------


def all_records(
    diagnosis_id: Optional[str] = None, verdict: Optional[str] = None
) -> list[ReviewRecord]:
    records = collection.all()
    if diagnosis_id:
        wanted = diagnosis_id.strip().lower()
        records = [r for r in records if r.diagnosis_id.lower() == wanted]
    if verdict:
        wanted_verdict = verdict.strip().lower()
        records = [r for r in records if r.verdict == wanted_verdict]
    return records


def get(review_id: str) -> Optional[ReviewRecord]:
    return collection.get(review_id)


def require(review_id: str) -> ReviewRecord:
    record = get(review_id)
    if record is None:
        raise NotFoundError(f"no review with id '{review_id}'")
    return record


def for_diagnosis(diagnosis_id: str) -> Optional[ReviewRecord]:
    wanted = diagnosis_id.strip().lower()
    return collection.first(lambda r: r.diagnosis_id.lower() == wanted)


# --- validation ---------------------------------------------------------------------------


def _validate_verdict_requirements(
    verdict: str,
    reason_code: Optional[str],
    notes: Optional[str],
    corrected_root_cause: Optional[str],
    corrected_osi_layer: Optional[str],
    corrected_category: Optional[str],
    corrected_fix_steps: list[str],
) -> None:
    if verdict not in VALID_VERDICTS:
        raise ValidationError(
            f"verdict must be one of {', '.join(VALID_VERDICTS)}, got '{verdict}'"
        )

    if verdict == "edited":
        if not (reason_code or "").strip():
            raise ValidationError("an 'edited' review requires a reason_code")
        has_correction = any(
            [
                (corrected_root_cause or "").strip(),
                (corrected_osi_layer or "").strip(),
                (corrected_category or "").strip(),
                [step for step in corrected_fix_steps if step.strip()],
            ]
        )
        if not has_correction:
            raise ValidationError(
                "an 'edited' review requires at least one correction: "
                "corrected_root_cause, corrected_osi_layer, corrected_category or "
                "corrected_fix_steps"
            )

    if verdict == "rejected":
        if not (reason_code or "").strip():
            raise ValidationError("a 'rejected' review requires a reason_code")
        if not (notes or "").strip():
            raise ValidationError("a 'rejected' review requires notes explaining why")

    if corrected_osi_layer and corrected_osi_layer not in {layer.value for layer in OSILayer}:
        raise ValidationError(
            f"corrected_osi_layer '{corrected_osi_layer}' is not a valid OSI layer"
        )
    if corrected_category and corrected_category not in {tag.value for tag in ConceptTag}:
        raise ValidationError(
            f"corrected_category '{corrected_category}' is not a valid category"
        )


def compute_agreement(
    diagnosis: DiagnosisRecord,
    verdict: str,
    corrected_root_cause: Optional[str] = None,
    corrected_osi_layer: Optional[str] = None,
    corrected_category: Optional[str] = None,
) -> AgreementRecord:
    """Whether the human agreed with the AI on root cause, OSI layer and category.

    Derived from what the reviewer actually did, not asked of them as a separate question:
    an accepted review agrees on everything, a rejected review disagrees on the root cause,
    and an edited review disagrees exactly where it supplied a different value.
    """
    if verdict == "accepted":
        return AgreementRecord(root_cause=True, osi_layer=True, category=True)

    if verdict == "rejected":
        # The reviewer threw out the cause. Layer and category count as agreed only if
        # they explicitly restated the AI's value.
        return AgreementRecord(
            root_cause=False,
            osi_layer=bool(corrected_osi_layer) and corrected_osi_layer == diagnosis.ai.osi_layer,
            category=bool(corrected_category) and corrected_category == diagnosis.ai.category,
        )

    # edited: a supplied correction that differs is a disagreement; anything not corrected
    # was left standing, which is agreement.
    return AgreementRecord(
        root_cause=not (corrected_root_cause or "").strip(),
        osi_layer=(not corrected_osi_layer) or corrected_osi_layer == diagnosis.ai.osi_layer,
        category=(not corrected_category) or corrected_category == diagnosis.ai.category,
    )


# --- creation -----------------------------------------------------------------------------


def create_review(
    diagnosis_id: str,
    verdict: str,
    reviewer: str = "human-reviewer",
    reason_code: Optional[str] = None,
    notes: Optional[str] = None,
    corrected_root_cause: Optional[str] = None,
    corrected_osi_layer: Optional[str] = None,
    corrected_category: Optional[str] = None,
    corrected_rule_ids: Optional[list[str]] = None,
    corrected_fix_steps: Optional[list[str]] = None,
) -> ReviewRecord:
    """Record one human verdict, enforcing every gate rule.

    Raises :class:`NotFoundError` for an unknown diagnosis, :class:`ConflictError` if the
    diagnosis has already been reviewed, and :class:`ValidationError` when the verdict's
    own requirements are not met.
    """
    normalised = (verdict or "").strip().lower()
    fix_steps = [step for step in (corrected_fix_steps or [])]
    rule_ids = [rid.strip().upper() for rid in (corrected_rule_ids or []) if rid.strip()]

    diagnosis = diagnosis_repo.require(diagnosis_id)

    existing = for_diagnosis(diagnosis.diagnosis_id)
    if existing is not None:
        raise ConflictError(
            f"diagnosis '{diagnosis.diagnosis_id}' has already been reviewed "
            f"({existing.verdict}, review {existing.review_id}). A diagnosis is reviewed "
            "once; the audit trail is not overwritten."
        )

    _validate_verdict_requirements(
        normalised,
        reason_code,
        notes,
        corrected_root_cause,
        corrected_osi_layer,
        corrected_category,
        fix_steps,
    )

    known_rule_ids = set(diagnosis.rule_ids)
    unknown = [rid for rid in rule_ids if rid not in known_rule_ids]
    if unknown:
        raise ValidationError(
            f"corrected_rule_ids {unknown} do not appear in this diagnosis's rule findings "
            f"({', '.join(sorted(known_rule_ids)) or 'none'}). A reviewer can narrow the "
            "fix to findings the engine actually reported, not invent new ones."
        )

    review = ReviewRecord(
        diagnosis_id=diagnosis.diagnosis_id,
        case_id=diagnosis.case_id,
        verdict=normalised,  # type: ignore[arg-type]
        reviewer=reviewer or "human-reviewer",
        reason_code=(reason_code or None),
        notes=(notes or None),
        corrected_root_cause=(corrected_root_cause or None),
        corrected_osi_layer=(corrected_osi_layer or None),
        corrected_category=(corrected_category or None),
        corrected_rule_ids=rule_ids,
        corrected_fix_steps=fix_steps,
        agreement=compute_agreement(
            diagnosis,
            normalised,
            corrected_root_cause,
            corrected_osi_layer,
            corrected_category,
        ),
    )

    collection.append(review)
    # The diagnosis now carries the verdict. It still is not applied — that needs a fix run.
    diagnosis_repo.set_review_outcome(
        diagnosis.diagnosis_id, review.review_id, VERDICT_TO_STATUS[normalised]
    )
    return review


def agreement_stats() -> dict[str, int]:
    """Counts for the AI-vs-human agreement metric. Computed, never hard-coded."""
    records = collection.all()
    stats = {
        "total": len(records),
        "accepted": 0,
        "edited": 0,
        "rejected": 0,
        "full_agreement": 0,
        "root_cause_disagreement": 0,
        "osi_layer_disagreement": 0,
        "category_disagreement": 0,
    }
    for record in records:
        stats[record.verdict] += 1
        if record.agreement.fully_agreed:
            stats["full_agreement"] += 1
        if not record.agreement.root_cause:
            stats["root_cause_disagreement"] += 1
        if not record.agreement.osi_layer:
            stats["osi_layer_disagreement"] += 1
        if not record.agreement.category:
            stats["category_disagreement"] += 1
    return stats
