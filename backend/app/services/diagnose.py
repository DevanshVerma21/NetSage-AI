"""The diagnosis service — the AI pipeline, orchestrated.

Ten steps, in order:

    1. prepare the structured request      6. validate the AIDiagnosis (at the schema boundary)
    2. run the deterministic rules         7. verify every evidence citation
    3. load the versioned prompt           8. reconcile AI against rules
    4. select the provider                 9. apply the confidence caps
    5. run the provider                   10. return the complete result

What this service deliberately does **not** do, because those belong to later phases:

* persist anything (Phase 3)
* expose an HTTP endpoint (Phase 3)
* apply or simulate a fix (Phase 3)
* perform or record a human review (Phase 3)

Every result it returns is marked ``status="awaiting_human_review"`` with ``applied=False``.
There is no code path here that can set either to anything else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from backend.app.ai import prompt_loader
from backend.app.ai.base import DiagnoseRequest, LLMProvider, ProviderResult
from backend.app.ai.confidence import ConfidenceDecision, cap_confidence
from backend.app.ai.evidence_verifier import EvidenceVerificationResult, verify_evidence
from backend.app.ai.factory import build_provider_with_fallback
from backend.app.ai.reconciler import ReconciliationResult, reconcile
from backend.app.models.case import Case
from backend.app.models.diagnosis import AIDiagnosis, ConfidenceLiteral
from backend.app.rules.engine import Finding, run_rules

AWAITING_REVIEW = "awaiting_human_review"


@dataclass
class DiagnosisResult:
    """Everything produced for one case: the proposal plus every independent check on it."""

    # --- provenance --------------------------------------------------------------------
    case_id: Optional[str]
    provider: str
    model: str
    prompt_name: str
    prompt_version: str
    prompt_sha256: str
    created_at: str

    # --- the deterministic half --------------------------------------------------------
    rule_findings: list[Finding]

    # --- the AI half -------------------------------------------------------------------
    ai: AIDiagnosis

    # --- the independent checks --------------------------------------------------------
    evidence_verification: EvidenceVerificationResult
    reconciliation: ReconciliationResult
    confidence: ConfidenceDecision

    # --- metadata ----------------------------------------------------------------------
    latency_ms: int
    token_usage: Optional[dict[str, int]] = None
    repair_attempts: int = 0
    provider_note: Optional[str] = None
    """Set when the requested provider was unavailable and mock was substituted."""

    # --- the human gate ----------------------------------------------------------------
    status: str = AWAITING_REVIEW
    applied: bool = False

    warnings: list[str] = field(default_factory=list)

    # --- convenience accessors ---------------------------------------------------------

    @property
    def evidence_integrity(self) -> str:
        return self.evidence_verification.status

    @property
    def model_confidence(self) -> ConfidenceLiteral:
        return self.confidence.model_confidence

    @property
    def effective_confidence(self) -> ConfidenceLiteral:
        return self.confidence.effective_confidence

    @property
    def agreement(self) -> str:
        return self.reconciliation.status

    @property
    def requires_human_review(self) -> bool:
        """Always true. Present so callers can assert on it rather than assume it."""
        return True

    def summary_lines(self) -> list[str]:
        """Compact human-readable summary, used by the CLI and the Phase 2 demo output."""
        lines = [
            f"case            : {self.case_id or '(ad-hoc)'}",
            f"provider/model  : {self.provider} / {self.model}",
            f"prompt          : {self.prompt_name} v{self.prompt_version} "
            f"({self.prompt_sha256[:12]}…)",
            f"rule findings   : {len(self.rule_findings)} "
            f"({', '.join(sorted({f.rule_id for f in self.rule_findings})) or 'none'})",
            f"root cause      : {self.ai.root_cause}",
            f"category / OSI  : {self.ai.category} / {self.ai.osi_layer}",
            f"model conf.     : {self.model_confidence.upper()} "
            f"({self.confidence.model_confidence_score:.2f})",
            f"effective conf. : {self.effective_confidence.upper()} "
            f"({self.confidence.effective_confidence_score:.2f})"
            + ("  [CAPPED]" if self.confidence.was_capped else ""),
            f"evidence        : {self.evidence_verification.verified_count}"
            f"/{self.evidence_verification.total_count} verified "
            f"-> integrity={self.evidence_integrity}",
            f"reconciliation  : {self.agreement}",
            f"status          : {self.status}  (applied={self.applied})",
        ]
        for warning in self.warnings:
            lines.append(f"warning         : {warning}")
        return lines


def diagnose_case(
    case: Case,
    provider: Optional[LLMProvider] = None,
    provider_name: Optional[str] = None,
) -> DiagnosisResult:
    """Run the full pipeline for a stored case."""
    findings = run_rules(case.lab_state, case.intended_flows)
    request = DiagnoseRequest.from_case(case, findings)
    return diagnose_request(
        request, provider=provider, provider_name=provider_name, findings=findings
    )


def diagnose_request(
    request: DiagnoseRequest,
    provider: Optional[LLMProvider] = None,
    provider_name: Optional[str] = None,
    findings: Optional[list[Finding]] = None,
) -> DiagnosisResult:
    """Run the full pipeline for an already-prepared request.

    Args:
        request: the structured request. Its ``rule_findings`` are used as-is.
        provider: an explicit provider instance, mainly for tests.
        provider_name: a provider name to build, overriding configuration.
        findings: the rule findings, if already computed. Defaults to the request's.
    """
    rule_findings = findings if findings is not None else list(request.rule_findings)

    # Steps 3 and 4: prompt identity, then provider.
    prompt = prompt_loader.load_prompt("diagnose_prompt")

    provider_note: Optional[str] = None
    if provider is None:
        provider, provider_note = build_provider_with_fallback(provider_name)

    # Step 5 and 6: run the provider. Schema validation happens inside it, at the boundary,
    # so an invalid response never reaches the verification stages.
    result: ProviderResult = provider.diagnose(request)
    diagnosis = result.diagnosis

    # Step 7: verify the evidence. The verifier is authoritative, not the model's claim.
    verification = verify_evidence(
        diagnosis.evidence,
        request.evidence_corpus(),
        insufficient_evidence=diagnosis.insufficient_evidence,
    )

    # Step 8: reconcile against the deterministic findings.
    reconciliation = reconcile(diagnosis, rule_findings)

    # Step 9: cap the confidence.
    confidence = cap_confidence(diagnosis, verification, reconciliation)

    # Step 10: assemble, collecting every warning a reviewer needs to see.
    warnings: list[str] = []
    if provider_note:
        warnings.append(provider_note)
    if (evidence_warning := verification.warning()) is not None:
        warnings.append(evidence_warning)
    if (reconciliation_warning := reconciliation.warning()) is not None:
        warnings.append(reconciliation_warning)
    if not diagnosis.confidence_score_matches_band:
        warnings.append(
            f"CALIBRATION: the model reported confidence '{diagnosis.confidence}' with "
            f"score {diagnosis.confidence_score:.2f}, which falls outside that band. Treat "
            "the numeric score with caution."
        )
    if confidence.was_capped:
        warnings.extend(confidence.cap_reasons)

    return DiagnosisResult(
        case_id=request.case_id,
        provider=result.provider,
        model=result.model,
        prompt_name=prompt.name,
        prompt_version=prompt.version,
        prompt_sha256=prompt.sha256,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        rule_findings=rule_findings,
        ai=diagnosis,
        evidence_verification=verification,
        reconciliation=reconciliation,
        confidence=confidence,
        latency_ms=result.latency_ms,
        token_usage=result.token_usage,
        repair_attempts=result.repair_attempts,
        provider_note=provider_note,
        warnings=warnings,
    )
