"""Simulated fix application, behind the human-review gate.

The entry point takes a **review id** and nothing else. That is the whole security design:
to apply a fix you must name a human verdict that already exists in storage, and the
mutations are then derived from the reviewed diagnosis's own deterministic findings. There
is no parameter through which a client can describe a change it wants made, and no way to
reach this code without a review.

Four states are refused, all with 409:

* the diagnosis has no review at all
* the review rejected the diagnosis
* the diagnosis has already been applied
* the reviewed diagnosis names a case that is no longer in the dataset (404 — nothing to
  simulate against)
"""

from __future__ import annotations

from typing import Optional

from backend.app.models.records import (
    APPLICABLE_VERDICTS,
    DiagnosisRecord,
    FixRunRecord,
    ReviewRecord,
)
from backend.app.services import case_repo, diagnosis_repo, fix_simulator, review_service
from backend.app.services.errors import ConflictError, NotFoundError
from backend.app.services.record_store import FIX_RUNS_FILE, JsonCollection

collection: JsonCollection[FixRunRecord] = JsonCollection(FIX_RUNS_FILE, FixRunRecord, "run_id")


# --- lookups ------------------------------------------------------------------------------


def all_records(
    diagnosis_id: Optional[str] = None,
    case_id: Optional[str] = None,
    review_id: Optional[str] = None,
) -> list[FixRunRecord]:
    """Stored fix runs, narrowed by any combination of the three filters.

    ``review_id`` is the most specific of them: a review may be applied once, so it selects
    at most one run. Every filter is optional and they compose, so passing none still
    returns the whole collection as before.
    """
    records = collection.all()
    if diagnosis_id:
        wanted = diagnosis_id.strip().lower()
        records = [r for r in records if r.diagnosis_id.lower() == wanted]
    if case_id:
        wanted_case = case_id.strip().lower()
        records = [r for r in records if (r.case_id or "").lower() == wanted_case]
    if review_id:
        wanted_review = review_id.strip().lower()
        records = [r for r in records if (r.review_id or "").lower() == wanted_review]
    return records


def get(run_id: str) -> Optional[FixRunRecord]:
    return collection.get(run_id)


def require(run_id: str) -> FixRunRecord:
    record = get(run_id)
    if record is None:
        raise NotFoundError(f"no fix run with id '{run_id}'")
    return record


def for_diagnosis(diagnosis_id: str) -> Optional[FixRunRecord]:
    wanted = diagnosis_id.strip().lower()
    return collection.first(lambda r: r.diagnosis_id.lower() == wanted)


# --- the gate -----------------------------------------------------------------------------


def _authorise(review_id: str) -> tuple[ReviewRecord, DiagnosisRecord]:
    """Resolve a review to the diagnosis it approves, or refuse.

    Note the direction of the lookup: review -> diagnosis. The client does not get to name
    the diagnosis, so it cannot pair a rejected diagnosis with somebody else's approval.
    """
    review = review_service.require(review_id)
    diagnosis = diagnosis_repo.require(review.diagnosis_id)

    if review.verdict not in APPLICABLE_VERDICTS:
        raise ConflictError(
            f"review '{review.review_id}' rejected this diagnosis, so no fix may be "
            "applied. A rejected diagnosis stays unapplied."
        )

    if diagnosis.applied:
        existing = for_diagnosis(diagnosis.diagnosis_id)
        suffix = f" (fix run {existing.run_id})" if existing else ""
        raise ConflictError(
            f"diagnosis '{diagnosis.diagnosis_id}' has already had a fix applied{suffix}."
        )

    return review, diagnosis


def check_can_apply(diagnosis_id: str) -> ReviewRecord:
    """Return the review that authorises a fix for this diagnosis, or refuse.

    Exists so an unreviewed diagnosis produces an honest 409 ("a human review is required")
    whether the caller comes in by diagnosis id or by review id.
    """
    diagnosis = diagnosis_repo.require(diagnosis_id)
    review = review_service.for_diagnosis(diagnosis.diagnosis_id)
    if review is None:
        raise ConflictError(
            f"diagnosis '{diagnosis.diagnosis_id}' is {diagnosis.status}: a human review is "
            "required before any fix can be applied."
        )
    _authorise(review.review_id)
    return review


# --- application --------------------------------------------------------------------------


def apply_reviewed_fix(review_id: str) -> FixRunRecord:
    """Simulate the approved fix and store the deterministic before/after verification."""
    review, diagnosis = _authorise(review_id)

    if not diagnosis.case_id:
        raise ConflictError(
            "this diagnosis was produced from an ad-hoc request rather than a stored case, "
            "so there is no lab model to simulate a fix against."
        )

    case = case_repo.get_case(diagnosis.case_id, use_cache=False)
    if case is None:
        raise NotFoundError(
            f"case '{diagnosis.case_id}' is no longer in the dataset, so its fix cannot be "
            "simulated."
        )

    # Reviewer edits win: when the reviewer narrowed the fix to particular findings, only
    # those findings' mutations are proposed.
    mutations = diagnosis.mutations(only_rule_ids=review.corrected_rule_ids or None)

    outcome = fix_simulator.apply_mutations(
        case.lab_state, mutations, intended_flows=case.intended_flows
    )

    run = FixRunRecord(
        diagnosis_id=diagnosis.diagnosis_id,
        review_id=review.review_id,
        case_id=case.case_id,
        verdict=review.verdict,
        mutations=outcome.mutations,
        findings_before=outcome.findings_before,
        findings_after=outcome.findings_after,
        resolved_rule_ids=outcome.resolved_rule_ids,
        new_rule_ids=outcome.new_rule_ids,
        remaining_rule_ids=outcome.remaining_rule_ids,
        verification_result=outcome.verification_result,  # type: ignore[arg-type]
        verification_summary=outcome.summary(),
    )
    collection.append(run)

    # ``applied`` becomes true only here, only after a simulation actually ran, and only
    # for an accepted or edited diagnosis (the record model re-checks that).
    diagnosis_repo.mark_applied(diagnosis.diagnosis_id)
    return run
