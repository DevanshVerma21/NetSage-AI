"""Deterministic AI-vs-ground-truth evaluation.

This module holds every *decision* the Phase 6 evaluation makes, and none of the I/O. The
batch script owns the API calls, the checkpoint file and the console; this module owns the
schema, the classification, the metrics, the candidate ranking and the report text — so all
of it is testable with mocked results and none of it needs a network.

Two rules shape the design:

* **The model never grades itself.** Every comparison here is a mechanical string/set
  operation against the stored ground truth. No LLM call exists in this file.
* **Ground truth is read-only.** Nothing here writes to ``data/cases.json``. The thresholds
  below were fixed before the first batch ran and are documented in
  ``docs/evaluation_methodology.md``; changing them to improve a score would invalidate the
  evaluation.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from backend.app.models.case import Case
from backend.app.models.diagnosis import (
    AIDiagnosis,
    ConfidenceLiteral,
    IntegrityLiteral,
    ReconciliationLiteral,
)

EvaluationStatusLiteral = Literal["completed", "failed"]
EvaluationResultLiteral = Literal["CORRECT", "PARTIAL", "INCORRECT", "UNABLE_TO_EVALUATE"]

RESULT_ORDER: tuple[EvaluationResultLiteral, ...] = (
    "CORRECT",
    "PARTIAL",
    "INCORRECT",
    "UNABLE_TO_EVALUATE",
)

# --- classification thresholds (fixed before the first batch; see the methodology doc) ---

KEYWORD_RATE_FOR_CORRECT = 0.5
"""At least half the ground-truth keywords must appear for a CORRECT verdict."""

KEYWORD_RATE_FOR_PARTIAL = 0.25
"""Below this, with the category also wrong, the diagnosis is INCORRECT rather than PARTIAL."""


def normalise(text: str) -> str:
    """Collapse whitespace and fold case, as the evidence verifier does."""
    return re.sub(r"\s+", " ", text or "").strip().lower()


# --- stored shapes ------------------------------------------------------------------------


class EvidenceCitation(BaseModel):
    """One citation as the model produced it, plus the verifier's verdict on it."""

    model_config = ConfigDict(extra="forbid")

    source_command: str
    excerpt: str
    why_it_matters: str
    verified: bool
    failure_reason: Optional[str] = None
    failure_detail: Optional[str] = None


class AgreementDetail(BaseModel):
    """The four mechanical comparisons behind the classification."""

    model_config = ConfigDict(extra="forbid")

    rule_agreement: bool
    """At least one expected rule was corroborated by the AI's category."""
    matched_expected_rule_ids: list[str] = Field(default_factory=list)
    missed_expected_rule_ids: list[str] = Field(default_factory=list)

    keyword_agreement: bool
    matched_keywords: list[str] = Field(default_factory=list)
    missed_keywords: list[str] = Field(default_factory=list)
    keyword_hit_rate: float = 0.0

    osi_agreement: bool
    category_agreement: bool


class EvaluationRecord(BaseModel):
    """One case's evaluation. This is the row that lands in evaluation_results.json.

    Carries no credential and no raw provider payload — only the diagnosis fields a reviewer
    or a metric needs.
    """

    model_config = ConfigDict(extra="forbid")

    # --- identity -----------------------------------------------------------------------
    case_id: str
    category: str
    severity: str

    # --- ground truth (copied for auditability, never recomputed from AI output) --------
    expected_rule_ids: list[str] = Field(default_factory=list)
    expected_root_cause_keywords: list[str] = Field(default_factory=list)
    expected_osi_layer: str = ""
    expected_category: str = ""
    expected_fault: str = ""
    fired_rule_ids: list[str] = Field(default_factory=list)

    # --- what the AI produced -----------------------------------------------------------
    ai_root_cause: Optional[str] = None
    ai_osi_layer: Optional[str] = None
    ai_category: Optional[str] = None
    ai_evidence: list[EvidenceCitation] = Field(default_factory=list)
    ai_insufficient_evidence: bool = False
    next_command: Optional[str] = None
    fix_steps: list[str] = Field(default_factory=list)

    # --- the independent checks ---------------------------------------------------------
    model_confidence: Optional[ConfidenceLiteral] = None
    effective_confidence: Optional[ConfidenceLiteral] = None
    confidence_was_capped: bool = False
    evidence_integrity: Optional[IntegrityLiteral] = None
    total_citations: int = 0
    verified_citations: int = 0
    failed_citations: int = 0
    reconciliation: Optional[ReconciliationLiteral] = None

    # --- provenance ---------------------------------------------------------------------
    provider: Optional[str] = None
    model: Optional[str] = None
    prompt_version: Optional[str] = None
    prompt_sha256: Optional[str] = None
    diagnosis_id: Optional[str] = None
    """The persisted DiagnosisRecord, so a human review can be attached to this evaluation."""

    # --- outcome ------------------------------------------------------------------------
    evaluation_status: EvaluationStatusLiteral
    evaluation_result: EvaluationResultLiteral
    agreement: Optional[AgreementDetail] = None
    classification_reason: str = ""
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    attempts: int = 1

    latency_ms: int = 0
    timestamp: str = ""

    # --- audit ---------------------------------------------------------------------------
    # Additive provenance only. A record produced under a prompt contract later found to be
    # defective stays in the file for auditability, but is not an official final result. No
    # comparison, metric or classification reads these fields — they exist so that "this row
    # must be re-run" is recorded rather than remembered.
    invalidated: bool = False
    invalidated_reason: Optional[str] = None
    requires_rerun: bool = False

    @property
    def succeeded(self) -> bool:
        return self.evaluation_status == "completed"

    @property
    def is_official(self) -> bool:
        """A completed record that has not been invalidated by a later contract fix."""
        return self.succeeded and not self.invalidated


# --- comparisons --------------------------------------------------------------------------


def _keyword_haystack(diagnosis: AIDiagnosis) -> str:
    """Where a ground-truth keyword is allowed to appear.

    The root cause is the primary target, but a fault named only in the remediation ("no ip
    helper-address") or in the reviewer note is still a fault the model identified, so those
    are included. Nothing outside the model's own diagnosis is included.
    """
    parts = [diagnosis.root_cause, diagnosis.notes_for_reviewer]
    for step in diagnosis.fix_steps:
        parts.append(step.rationale)
        parts.extend(step.cli_commands)
    return normalise(" ".join(part for part in parts if part))


def compare(case: Case, diagnosis: AIDiagnosis, fired_rule_ids: Iterable[str],
            matched_rule_ids: Iterable[str]) -> AgreementDetail:
    """Run the four comparisons of §6 against the stored ground truth.

    Args:
        case: the ground truth. Read only.
        diagnosis: what the model returned.
        fired_rule_ids: rule ids the deterministic engine reported for this case.
        matched_rule_ids: rule ids the *existing* reconciler judged corroborated by the AI's
            category. Reused rather than recomputed so rule agreement means exactly what the
            pipeline already decided it means.
    """
    expected_rules = sorted(set(case.expected_rule_ids))
    corroborated = set(matched_rule_ids) if diagnosis.claims_a_root_cause() else set()
    matched_rules = sorted(corroborated & set(expected_rules))
    missed_rules = sorted(set(expected_rules) - corroborated)

    haystack = _keyword_haystack(diagnosis) if diagnosis.claims_a_root_cause() else ""
    keywords = list(case.expected_root_cause_keywords)
    matched_keywords = [kw for kw in keywords if normalise(kw) and normalise(kw) in haystack]
    missed_keywords = [kw for kw in keywords if kw not in matched_keywords]
    hit_rate = (len(matched_keywords) / len(keywords)) if keywords else 0.0

    return AgreementDetail(
        rule_agreement=bool(matched_rules),
        matched_expected_rule_ids=matched_rules,
        missed_expected_rule_ids=missed_rules,
        keyword_agreement=hit_rate >= KEYWORD_RATE_FOR_CORRECT,
        matched_keywords=matched_keywords,
        missed_keywords=missed_keywords,
        keyword_hit_rate=round(hit_rate, 4),
        osi_agreement=diagnosis.claims_a_root_cause()
        and diagnosis.osi_layer == case.osi_layer.value,
        category_agreement=diagnosis.claims_a_root_cause()
        and diagnosis.category == case.concept_tag.value,
    )


def classify(
    agreement: AgreementDetail,
    evidence_integrity: IntegrityLiteral,
    declined: bool,
) -> tuple[EvaluationResultLiteral, str]:
    """Turn the comparisons into one of the four verdicts, with the reason recorded.

    Order matters and is documented in ``docs/evaluation_methodology.md``:

    1. the model declined to diagnose            -> UNABLE_TO_EVALUATE
    2. category + OSI + keywords + rule + evidence all hold -> CORRECT
    3. category wrong *and* almost no keyword overlap       -> INCORRECT
    4. evidence integrity failed with the category wrong    -> INCORRECT
    5. anything in between                                  -> PARTIAL
    """
    if declined:
        return (
            "UNABLE_TO_EVALUATE",
            "The model reported insufficient evidence and asserted no root cause, so there "
            "is no diagnosis to score against the ground truth.",
        )

    if (
        agreement.category_agreement
        and agreement.osi_agreement
        and agreement.keyword_hit_rate >= KEYWORD_RATE_FOR_CORRECT
        and agreement.rule_agreement
        and not agreement.missed_expected_rule_ids
        and evidence_integrity != "failed"
    ):
        return (
            "CORRECT",
            f"Category and OSI layer match the ground truth, "
            f"{len(agreement.matched_keywords)}/"
            f"{len(agreement.matched_keywords) + len(agreement.missed_keywords)} expected "
            f"keywords appear in the diagnosis, and "
            f"{', '.join(agreement.matched_expected_rule_ids)} corroborates it.",
        )

    if not agreement.category_agreement and agreement.keyword_hit_rate < KEYWORD_RATE_FOR_PARTIAL:
        return (
            "INCORRECT",
            f"The AI's category does not match the ground truth and only "
            f"{agreement.keyword_hit_rate:.0%} of the expected root-cause keywords appear, "
            "so the fault was not identified.",
        )

    if evidence_integrity == "failed" and not agreement.category_agreement:
        return (
            "INCORRECT",
            "Evidence verification failed — no citation could be located in the supplied "
            "output — and the category does not match the ground truth, so nothing in the "
            "diagnosis is both correct and substantiated.",
        )

    missing: list[str] = []
    if not agreement.category_agreement:
        missing.append("category differs")
    if not agreement.osi_agreement:
        missing.append("OSI layer differs")
    if agreement.keyword_hit_rate < KEYWORD_RATE_FOR_CORRECT:
        missing.append(
            f"only {agreement.keyword_hit_rate:.0%} of expected keywords present"
        )
    if not agreement.rule_agreement:
        missing.append("no expected rule corroborated")
    if agreement.missed_expected_rule_ids:
        missing.append(
            f"secondary finding(s) {', '.join(agreement.missed_expected_rule_ids)} not covered"
        )
    if evidence_integrity != "passed":
        missing.append(f"evidence integrity {evidence_integrity}")

    return (
        "PARTIAL",
        "The diagnosis overlaps the ground truth but is not fully correct: "
        + "; ".join(missing)
        + ".",
    )


# --- record construction ------------------------------------------------------------------


def _citations(result) -> list[EvidenceCitation]:
    """Project the verifier's verdict onto the model's citations.

    A failed citation keeps its original text and gains the reason it failed. It is never
    dropped, repaired or rewritten — that is the whole point of storing it.
    """
    verification = result.evidence_verification
    failed_by_index = {item.index: item for item in verification.failed_items}
    out: list[EvidenceCitation] = []
    for index, citation in enumerate(result.ai.evidence):
        failure = failed_by_index.get(index)
        out.append(
            EvidenceCitation(
                source_command=citation.source_command,
                excerpt=citation.excerpt,
                why_it_matters=citation.why_it_matters,
                verified=failure is None,
                failure_reason=failure.reason if failure else None,
                failure_detail=failure.detail if failure else None,
            )
        )
    return out


def _fix_step_lines(diagnosis: AIDiagnosis) -> list[str]:
    return [
        f"{step.order}. [{step.device}] {'; '.join(step.cli_commands)} — {step.rationale} "
        f"(risk={step.risk})"
        for step in diagnosis.fix_steps
    ]


def record_from_result(case: Case, result, diagnosis_id: Optional[str] = None,
                       attempts: int = 1) -> EvaluationRecord:
    """Build the stored evaluation row from a completed pipeline result."""
    diagnosis: AIDiagnosis = result.ai
    fired = sorted({finding.rule_id for finding in result.rule_findings})
    agreement = compare(
        case, diagnosis, fired, result.reconciliation.matched_rule_ids
    )
    verdict, reason = classify(
        agreement, result.evidence_integrity, not diagnosis.claims_a_root_cause()
    )

    return EvaluationRecord(
        case_id=case.case_id,
        category=case.concept_tag.value,
        severity=case.severity.value,
        expected_rule_ids=list(case.expected_rule_ids),
        expected_root_cause_keywords=list(case.expected_root_cause_keywords),
        expected_osi_layer=case.osi_layer.value,
        expected_category=case.concept_tag.value,
        expected_fault=case.expected_fault,
        fired_rule_ids=fired,
        ai_root_cause=diagnosis.root_cause,
        ai_osi_layer=diagnosis.osi_layer,
        ai_category=diagnosis.category,
        ai_evidence=_citations(result),
        ai_insufficient_evidence=diagnosis.insufficient_evidence,
        next_command=diagnosis.next_command,
        fix_steps=_fix_step_lines(diagnosis),
        model_confidence=result.model_confidence,
        effective_confidence=result.effective_confidence,
        confidence_was_capped=result.confidence.was_capped,
        evidence_integrity=result.evidence_integrity,
        total_citations=result.evidence_verification.total_count,
        verified_citations=result.evidence_verification.verified_count,
        failed_citations=result.evidence_verification.failed_count,
        reconciliation=result.reconciliation.status,
        provider=result.provider,
        model=result.model,
        prompt_version=result.prompt_version,
        prompt_sha256=result.prompt_sha256,
        diagnosis_id=diagnosis_id,
        evaluation_status="completed",
        evaluation_result=verdict,
        agreement=agreement,
        classification_reason=reason,
        attempts=attempts,
        latency_ms=result.latency_ms,
        timestamp=result.created_at,
    )


def failure_record(case: Case, error: BaseException, attempts: int, timestamp: str,
                   provider: str, model: str) -> EvaluationRecord:
    """Record a case whose Gemini call permanently failed.

    A failed case is stored, counted and reported. There is no code path that drops one.
    """
    return EvaluationRecord(
        case_id=case.case_id,
        category=case.concept_tag.value,
        severity=case.severity.value,
        expected_rule_ids=list(case.expected_rule_ids),
        expected_root_cause_keywords=list(case.expected_root_cause_keywords),
        expected_osi_layer=case.osi_layer.value,
        expected_category=case.concept_tag.value,
        expected_fault=case.expected_fault,
        provider=provider,
        model=model,
        evaluation_status="failed",
        evaluation_result="UNABLE_TO_EVALUATE",
        classification_reason=(
            "The diagnosis could not be produced, so no comparison against the ground truth "
            "was possible."
        ),
        error_type=type(error).__name__,
        error_message=str(error),
        attempts=attempts,
        timestamp=timestamp,
    )


# --- metrics ------------------------------------------------------------------------------


def _counts(values: Iterable[str], vocabulary: Iterable[str]) -> dict[str, int]:
    """Count ``values``, guaranteeing a zero entry for every term in ``vocabulary``."""
    tally = Counter(values)
    return {term: tally.get(term, 0) for term in vocabulary}


def compute_metrics(records: list[EvaluationRecord]) -> dict:
    """Every number in the reports, calculated from the stored records.

    Nothing is hard-coded: pass in an empty list and every count is zero.
    """
    completed = [r for r in records if r.succeeded]
    failed = [r for r in records if not r.succeeded]
    scored = [r for r in completed if r.agreement is not None]

    results = _counts((r.evaluation_result for r in records), RESULT_ORDER)

    agreement = {
        "rule_agreement": sum(1 for r in scored if r.agreement.rule_agreement),
        "root_cause_agreement": sum(1 for r in scored if r.agreement.keyword_agreement),
        "osi_agreement": sum(1 for r in scored if r.agreement.osi_agreement),
        "category_agreement": sum(1 for r in scored if r.agreement.category_agreement),
        "scored_cases": len(scored),
        "mean_keyword_hit_rate": round(
            sum(r.agreement.keyword_hit_rate for r in scored) / len(scored), 4
        )
        if scored
        else 0.0,
    }

    total_citations = sum(r.total_citations for r in completed)
    verified_citations = sum(r.verified_citations for r in completed)
    evidence = {
        "integrity": _counts(
            (r.evidence_integrity for r in completed if r.evidence_integrity),
            ("passed", "partial", "failed"),
        ),
        "total_citations": total_citations,
        "verified_citations": verified_citations,
        "failed_citations": sum(r.failed_citations for r in completed),
        "verification_rate": round(verified_citations / total_citations, 4)
        if total_citations
        else 0.0,
    }

    bands = ("low", "medium", "high")
    confidence = {
        "model": _counts((r.model_confidence for r in completed if r.model_confidence), bands),
        "effective": _counts(
            (r.effective_confidence for r in completed if r.effective_confidence), bands
        ),
        "capped": sum(1 for r in completed if r.confidence_was_capped),
        # The responsible-AI cross-tabs: confidence against actual correctness.
        "high_confidence_incorrect": sum(
            1
            for r in completed
            if r.effective_confidence == "high" and r.evaluation_result == "INCORRECT"
        ),
        "high_confidence_partial": sum(
            1
            for r in completed
            if r.effective_confidence == "high" and r.evaluation_result == "PARTIAL"
        ),
        "low_confidence_correct": sum(
            1
            for r in completed
            if r.effective_confidence == "low" and r.evaluation_result == "CORRECT"
        ),
        "medium_confidence_correct": sum(
            1
            for r in completed
            if r.effective_confidence == "medium" and r.evaluation_result == "CORRECT"
        ),
        "model_high_but_capped": sum(
            1
            for r in completed
            if r.model_confidence == "high" and r.effective_confidence != "high"
        ),
    }

    reconciliation = _counts(
        (r.reconciliation for r in completed if r.reconciliation),
        ("agree", "partial", "ai_only", "rules_only", "conflict"),
    )

    latencies = sorted(r.latency_ms for r in completed if r.latency_ms)

    return {
        "totals": {
            "total_cases": len(records),
            "successful": len(completed),
            "failed": len(failed),
            "failed_case_ids": [r.case_id for r in failed],
        },
        "results": results,
        "accuracy": {
            "correct_rate": round(results["CORRECT"] / len(records), 4) if records else 0.0,
            "correct_or_partial_rate": round(
                (results["CORRECT"] + results["PARTIAL"]) / len(records), 4
            )
            if records
            else 0.0,
        },
        "agreement": agreement,
        "evidence": evidence,
        "confidence": confidence,
        "reconciliation": reconciliation,
        "by_category": _by_category(records),
        "latency_ms": {
            "min": latencies[0] if latencies else 0,
            "median": latencies[len(latencies) // 2] if latencies else 0,
            "max": latencies[-1] if latencies else 0,
            "mean": round(sum(latencies) / len(latencies)) if latencies else 0,
        },
        "providers": sorted({r.provider for r in records if r.provider}),
        "models": sorted({r.model for r in records if r.model}),
        "prompt_versions": sorted({r.prompt_version for r in records if r.prompt_version}),
    }


def _by_category(records: list[EvaluationRecord]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for record in records:
        bucket = out.setdefault(
            record.category, {name: 0 for name in RESULT_ORDER} | {"total": 0}
        )
        bucket[record.evaluation_result] += 1
        bucket["total"] += 1
    return dict(sorted(out.items()))


# --- human review queue -------------------------------------------------------------------

# Priority order from §11. Lower number = reviewed first.
CANDIDATE_PRIORITIES: tuple[tuple[int, str], ...] = (
    (1, "evaluation_result = INCORRECT"),
    (2, "evaluation_result = PARTIAL"),
    (3, "evidence_integrity = failed"),
    (4, "reconciliation = conflict"),
    (5, "high effective confidence on a non-CORRECT diagnosis"),
    (6, "suspiciously unsupported diagnosis"),
)


def candidate_reasons(record: EvaluationRecord) -> list[tuple[int, str]]:
    """Every §11 trigger this record fires, as (priority, reason) pairs.

    A record may fire several; the queue is ordered by the strongest one but every reason is
    stored, because the reviewer needs to know all of them.
    """
    reasons: list[tuple[int, str]] = []

    if record.evaluation_result == "INCORRECT":
        reasons.append((1, "Classified INCORRECT against the stored ground truth."))
    elif record.evaluation_result == "PARTIAL":
        reasons.append((2, "Classified PARTIAL against the stored ground truth."))

    if record.evidence_integrity == "failed":
        reasons.append(
            (3, "Evidence integrity FAILED — no citation could be located in the supplied "
                "output.")
        )
    if record.reconciliation == "conflict":
        reasons.append(
            (4, "The diagnosis conflicts with what the deterministic rule engine observed.")
        )
    if record.effective_confidence == "high" and record.evaluation_result in {
        "INCORRECT",
        "PARTIAL",
    }:
        reasons.append(
            (5, f"HIGH effective confidence on a {record.evaluation_result} diagnosis — a "
                "confidently wrong answer is the most dangerous failure mode.")
        )
    if record.evaluation_status == "failed":
        reasons.append(
            (1, f"The Gemini call failed permanently ({record.error_type}), so the case has "
                "no diagnosis at all.")
        )
    if record.succeeded and record.verified_citations == 0 and not record.ai_insufficient_evidence:
        reasons.append(
            (6, "Suspiciously unsupported: the model asserted a root cause with no verified "
                "citation.")
        )
    if record.reconciliation == "ai_only":
        reasons.append(
            (6, "Uncorroborated: the AI asserted a fault the deterministic checker did not "
                "detect.")
        )

    return sorted(set(reasons))


def select_review_candidates(records: list[EvaluationRecord]) -> list[dict]:
    """Rank the cases a human should look at first. Selects; never decides.

    Every entry is created with ``status="pending"``. There is no argument to this function
    that can produce any other status, and nothing here writes a human decision.
    """
    candidates: list[dict] = []
    for record in records:
        reasons = candidate_reasons(record)
        if not reasons:
            continue
        priority = min(priority for priority, _ in reasons)
        candidates.append(
            {
                "case_id": record.case_id,
                "diagnosis_id": record.diagnosis_id,
                "priority": priority,
                "priority_label": next(
                    label for level, label in CANDIDATE_PRIORITIES if level == priority
                ),
                "ai_diagnosis": {
                    "root_cause": record.ai_root_cause,
                    "osi_layer": record.ai_osi_layer,
                    "category": record.ai_category,
                    "next_command": record.next_command,
                    "fix_steps": record.fix_steps,
                    "insufficient_evidence": record.ai_insufficient_evidence,
                },
                "expected_diagnosis": {
                    "expected_fault": record.expected_fault,
                    "osi_layer": record.expected_osi_layer,
                    "category": record.expected_category,
                    "expected_rule_ids": record.expected_rule_ids,
                    "expected_root_cause_keywords": record.expected_root_cause_keywords,
                },
                "model_confidence": record.model_confidence,
                "effective_confidence": record.effective_confidence,
                "evidence_integrity": record.evidence_integrity,
                "reconciliation": record.reconciliation,
                "evaluation_result": record.evaluation_result,
                "reason_for_review": [reason for _, reason in reasons],
                "status": "pending",
            }
        )

    # Strongest trigger first, then case id so the queue is stable across regenerations.
    return sorted(candidates, key=lambda c: (c["priority"], c["case_id"]))


# --- reports ------------------------------------------------------------------------------

MATRIX_COLUMNS = (
    "case_id",
    "category",
    "severity",
    "expected_rules",
    "ai_root_cause",
    "evaluation_result",
    "model_confidence",
    "effective_confidence",
    "evidence_integrity",
    "reconciliation",
)


def matrix_rows(records: list[EvaluationRecord]) -> list[dict[str, str]]:
    """Exactly one row per record, in case-id order, with the §10 columns."""
    rows = [
        {
            "case_id": r.case_id,
            "category": r.category,
            "severity": r.severity,
            "expected_rules": " ".join(r.expected_rule_ids),
            "ai_root_cause": " ".join((r.ai_root_cause or "").split()),
            "evaluation_result": r.evaluation_result,
            "model_confidence": r.model_confidence or "",
            "effective_confidence": r.effective_confidence or "",
            "evidence_integrity": r.evidence_integrity or "",
            "reconciliation": r.reconciliation or "",
        }
        for r in records
    ]
    return sorted(rows, key=lambda row: row["case_id"])


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    out.extend("| " + " | ".join(row) + " |" for row in rows)
    return out


def _pct(count: int, total: int) -> str:
    return f"{count} ({count / total:.0%})" if total else f"{count} (—)"


def render_markdown(metrics: dict, records: list[EvaluationRecord]) -> str:
    """The human-readable report. Every figure comes from ``metrics``."""
    totals = metrics["totals"]
    total = totals["total_cases"]
    results = metrics["results"]
    agreement = metrics["agreement"]
    scored = agreement["scored_cases"]
    evidence = metrics["evidence"]
    confidence = metrics["confidence"]

    lines = [
        "# NetSage AI — 40-case Gemini evaluation",
        "",
        "Every figure below is calculated from `data/evaluation_results.json`. Nothing is "
        "hard-coded; regenerate with `python -m backend.scripts.build_evaluation_reports`.",
        "",
        f"* provider / model: **{', '.join(metrics['providers']) or '—'}** / "
        f"**{', '.join(metrics['models']) or '—'}**",
        f"* prompt version: {', '.join(metrics['prompt_versions']) or '—'}",
        f"* cases evaluated: **{total}** — {totals['successful']} successful, "
        f"{totals['failed']} failed",
        f"* latency: min {metrics['latency_ms']['min']} ms · median "
        f"{metrics['latency_ms']['median']} ms · max {metrics['latency_ms']['max']} ms",
        "",
        "The AI never graded itself: every comparison in this report is a mechanical "
        "set/string operation against `data/cases.json`, which was not modified after the "
        "batch ran. See `docs/evaluation_methodology.md`.",
        "",
        "## 1. AI vs ground truth",
        "",
    ]
    lines += _table(
        ["Result", "Cases", "Share"],
        [[name, str(results[name]), f"{results[name] / total:.0%}" if total else "—"]
         for name in RESULT_ORDER],
    )
    lines += [
        "",
        "## 2. Agreement dimensions",
        "",
        f"Measured over the {scored} case(s) that produced a scoreable diagnosis.",
        "",
    ]
    lines += _table(
        ["Dimension", "Agreed"],
        [
            ["Rule agreement (an expected rule corroborated)",
             _pct(agreement["rule_agreement"], scored)],
            ["Root-cause keyword agreement (≥50% of keywords)",
             _pct(agreement["root_cause_agreement"], scored)],
            ["OSI layer agreement", _pct(agreement["osi_agreement"], scored)],
            ["Category agreement", _pct(agreement["category_agreement"], scored)],
            ["Mean keyword hit rate", f"{agreement['mean_keyword_hit_rate']:.0%}"],
        ],
    )
    lines += [
        "",
        "## 3. Evidence integrity",
        "",
    ]
    lines += _table(
        ["Integrity", "Cases"],
        [[name, str(count)] for name, count in evidence["integrity"].items()],
    )
    lines += [
        "",
        f"Citations: **{evidence['total_citations']}** total · "
        f"{evidence['verified_citations']} verified · {evidence['failed_citations']} failed "
        f"· verification rate **{evidence['verification_rate']:.1%}**.",
        "",
        "Failed citations are stored verbatim in the results file. None was overwritten, "
        "repaired or discarded.",
        "",
        "## 4. Confidence",
        "",
    ]
    lines += _table(
        ["Band", "Model confidence", "Effective confidence"],
        [[band, str(confidence["model"][band]), str(confidence["effective"][band])]
         for band in ("high", "medium", "low")],
    )
    lines += [
        "",
        f"* capped by the deterministic checks: **{confidence['capped']}** case(s) "
        f"({confidence['model_high_but_capped']} of them claimed HIGH and were reduced)",
        f"* high-confidence INCORRECT: **{confidence['high_confidence_incorrect']}**",
        f"* high-confidence PARTIAL: **{confidence['high_confidence_partial']}**",
        f"* low-confidence CORRECT: **{confidence['low_confidence_correct']}**",
        f"* medium-confidence CORRECT: **{confidence['medium_confidence_correct']}**",
        "",
        "## 5. Reconciliation against the rule engine",
        "",
    ]
    lines += _table(
        ["Status", "Cases"],
        [[name, str(count)] for name, count in metrics["reconciliation"].items()],
    )
    lines += ["", "## 6. Result by category", ""]
    lines += _table(
        ["Category", "Total", *RESULT_ORDER],
        [[name, str(bucket["total"]), *[str(bucket[key]) for key in RESULT_ORDER]]
         for name, bucket in metrics["by_category"].items()],
    )

    if totals["failed"]:
        lines += ["", "## 7. Failed evaluations", ""]
        lines += _table(
            ["Case", "Error", "Attempts", "Message"],
            [[r.case_id, r.error_type or "", str(r.attempts),
              " ".join((r.error_message or "").split())[:160]]
             for r in records if not r.succeeded],
        )
    else:
        lines += [
            "",
            "## 7. Failed evaluations",
            "",
            "None — every case produced a diagnosis.",
        ]

    lines += ["", "## 8. Per-case matrix", ""]
    lines += _table(
        ["Case", "Category", "Result", "Model conf.", "Effective conf.", "Evidence",
         "Reconciliation"],
        [[row["case_id"], row["category"], row["evaluation_result"],
          row["model_confidence"], row["effective_confidence"], row["evidence_integrity"],
          row["reconciliation"]]
         for row in matrix_rows(records)],
    )
    lines += [
        "",
        "Full per-case detail, including every citation and the classification reason, is in "
        "`data/evaluation_results.json`; the machine-readable summary is in "
        "`reports/ai_evaluation.json` and the flat matrix in "
        "`reports/case_evaluation_matrix.csv`.",
        "",
    ]
    return "\n".join(lines)
