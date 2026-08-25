"""All ``/api`` routes.

One module because the surface is small and the reading order matters: health, then the
case library, then the deterministic checker, then diagnosis, then the human gate, then the
simulated fix. That is also the order of the demo flow.

Two things no route in this file does: expose an environment variable or a credential
(``/health`` reports *whether* a provider is configured, never the key), and accept a
configuration change from the client.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from backend.app import __version__
from backend.app.api.schemas import (
    ApplyFixRequestBody,
    DiagnoseRequestBody,
    HealthResponse,
    ReviewRequestBody,
    RuleCheckRequest,
    RuleCheckResponse,
)
from backend.app.config import get_settings
from backend.app.models.case import Case, CaseSummary
from backend.app.models.records import EXECUTION_SCOPE, DiagnosisRecord, FixRunRecord, ReviewRecord
from backend.app.rules.engine import mandatory_rule_ids, registry, run_rules
from backend.app.services import (
    case_repo,
    diagnose,
    diagnosis_repo,
    fix_service,
    review_service,
)
from backend.app.services.errors import ServiceError, ValidationError

api_router = APIRouter(prefix="/api")


def _translate(error: ServiceError) -> HTTPException:
    """Service errors already know their status code; the router only forwards it."""
    return HTTPException(status_code=error.status_code, detail=error.message)


# --- health -------------------------------------------------------------------------------


@api_router.get("/health", response_model=HealthResponse, tags=["meta"])
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        version=__version__,
        cases_loaded=len(case_repo.all_cases()),
        rules_registered=len(registry()),
        mandatory_rules=mandatory_rule_ids(),
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        provider_configured=settings.provider_is_configured(),
        execution_scope=EXECUTION_SCOPE,
    )


# --- case library -------------------------------------------------------------------------


@api_router.get("/cases", response_model=list[CaseSummary], tags=["cases"])
def list_cases(
    category: Optional[str] = Query(default=None, description="Concept tag, e.g. VLAN"),
    severity: Optional[str] = Query(default=None, description="Low | Medium | High | Critical"),
    osi_layer: Optional[str] = Query(default=None, description="L1 … L7"),
    q: Optional[str] = Query(default=None, description="Free text over title and symptom"),
) -> list[CaseSummary]:
    cases = case_repo.all_cases()

    if category:
        wanted = category.strip().lower()
        cases = [c for c in cases if c.concept_tag.value.lower() == wanted]
    if severity:
        wanted = severity.strip().lower()
        cases = [c for c in cases if c.severity.value.lower() == wanted]
    if osi_layer:
        wanted = osi_layer.strip().lower()
        cases = [c for c in cases if c.osi_layer.value.lower() == wanted]
    if q:
        needle = q.strip().lower()
        cases = [
            c
            for c in cases
            if needle in c.title.lower()
            or needle in c.symptom.lower()
            or needle in c.topology_note.lower()
        ]

    return [CaseSummary.from_case(case) for case in cases]


@api_router.get("/cases/{case_id}", response_model=Case, tags=["cases"])
def get_case(case_id: str) -> Case:
    case = case_repo.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"no case with id '{case_id}'")
    return case


# --- the deterministic checker ------------------------------------------------------------


@api_router.post("/rules/check", response_model=RuleCheckResponse, tags=["rules"])
def check_rules(body: RuleCheckRequest) -> RuleCheckResponse:
    """Run the deterministic engine. No AI is involved on this path at all."""
    if body.case_id:
        case = case_repo.get_case(body.case_id)
        if case is None:
            raise HTTPException(status_code=404, detail=f"no case with id '{body.case_id}'")
        state = case.lab_state
        flows = list(case.intended_flows)
        case_id: Optional[str] = case.case_id
    elif body.lab_state is not None:
        state = body.lab_state
        flows = list(body.intended_flows)
        case_id = None
    else:
        raise HTTPException(
            status_code=422, detail="supply either case_id or lab_state"
        )

    unknown = [rid for rid in body.only if rid.upper() not in registry()]
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown rule ids: {unknown}")

    findings = run_rules(state, flows, only=[r.upper() for r in body.only] or None)
    return RuleCheckResponse(
        case_id=case_id,
        findings=findings,
        rule_ids=sorted({finding.rule_id for finding in findings}),
        finding_count=len(findings),
    )


# --- diagnosis ----------------------------------------------------------------------------


@api_router.post("/diagnose", response_model=DiagnosisRecord, status_code=201, tags=["diagnose"])
def create_diagnosis(body: DiagnoseRequestBody) -> DiagnosisRecord:
    """Run the AI pipeline and persist the proposal.

    The stored record is always ``awaiting_human_review`` with ``applied=false``. No
    parameter on this endpoint can change that, and no fix is applied here.
    """
    case = case_repo.get_case(body.case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"no case with id '{body.case_id}'")

    result = diagnose.diagnose_case(case, provider_name=body.provider)
    return diagnosis_repo.save(result)


@api_router.get("/diagnoses", response_model=list[DiagnosisRecord], tags=["diagnose"])
def list_diagnoses(
    case_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None, description="e.g. awaiting_human_review"),
) -> list[DiagnosisRecord]:
    return diagnosis_repo.all_records(case_id=case_id, status=status)


@api_router.get("/diagnoses/{diagnosis_id}", response_model=DiagnosisRecord, tags=["diagnose"])
def get_diagnosis(diagnosis_id: str) -> DiagnosisRecord:
    try:
        return diagnosis_repo.require(diagnosis_id)
    except ServiceError as error:
        raise _translate(error) from error


# --- the human gate -----------------------------------------------------------------------


@api_router.post("/reviews", response_model=ReviewRecord, status_code=201, tags=["reviews"])
def create_review(body: ReviewRequestBody) -> ReviewRecord:
    try:
        return review_service.create_review(
            diagnosis_id=body.diagnosis_id,
            verdict=body.verdict,
            reviewer=body.reviewer,
            reason_code=body.reason_code,
            notes=body.notes,
            corrected_root_cause=body.corrected_root_cause,
            corrected_osi_layer=body.corrected_osi_layer,
            corrected_category=body.corrected_category,
            corrected_rule_ids=body.corrected_rule_ids,
            corrected_fix_steps=body.corrected_fix_steps,
        )
    except ServiceError as error:
        raise _translate(error) from error


@api_router.get("/reviews", response_model=list[ReviewRecord], tags=["reviews"])
def list_reviews(
    diagnosis_id: Optional[str] = Query(default=None),
    verdict: Optional[str] = Query(default=None),
) -> list[ReviewRecord]:
    if verdict and verdict.strip().lower() not in review_service.VALID_VERDICTS:
        raise _translate(ValidationError(f"unknown verdict '{verdict}'"))
    return review_service.all_records(diagnosis_id=diagnosis_id, verdict=verdict)


@api_router.get("/reviews/{review_id}", response_model=ReviewRecord, tags=["reviews"])
def get_review(review_id: str) -> ReviewRecord:
    try:
        return review_service.require(review_id)
    except ServiceError as error:
        raise _translate(error) from error


# --- the simulated fix --------------------------------------------------------------------


@api_router.post("/fixes/apply", response_model=FixRunRecord, status_code=201, tags=["fixes"])
def apply_fix(body: ApplyFixRequestBody) -> FixRunRecord:
    """Simulate the approved fix against a copy of the lab model.

    Takes a review id and nothing else. The mutations come from the reviewed diagnosis's
    deterministic findings, so a client cannot describe a change of its own.
    """
    try:
        review_id = body.review_id
        if review_id is None:
            # The server resolves the approval itself; an unreviewed diagnosis is refused
            # here rather than being silently treated as approved.
            review_id = fix_service.check_can_apply(body.diagnosis_id or "").review_id
        return fix_service.apply_reviewed_fix(review_id)
    except ServiceError as error:
        raise _translate(error) from error


@api_router.get("/fixes", response_model=list[FixRunRecord], tags=["fixes"])
def list_fixes(
    diagnosis_id: Optional[str] = Query(default=None),
    case_id: Optional[str] = Query(default=None),
) -> list[FixRunRecord]:
    return fix_service.all_records(diagnosis_id=diagnosis_id, case_id=case_id)


@api_router.get("/fixes/{run_id}", response_model=FixRunRecord, tags=["fixes"])
def get_fix_run(run_id: str) -> FixRunRecord:
    try:
        return fix_service.require(run_id)
    except ServiceError as error:
        raise _translate(error) from error
