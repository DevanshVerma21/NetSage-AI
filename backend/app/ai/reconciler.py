"""Deterministic reconciliation of the AI diagnosis against the rule findings.

No language model is involved in deciding this. Asking a model to grade its own agreement
with the rule engine would defeat the purpose of having an independent check.

The five states are mutually exclusive and exhaustive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from backend.app.models.diagnosis import AIDiagnosis
from backend.app.rules.engine import Finding

ReconciliationStatus = Literal["agree", "partial", "ai_only", "rules_only", "conflict"]


@dataclass
class ReconciliationResult:
    status: ReconciliationStatus
    reason: str
    matched_rule_ids: list[str] = field(default_factory=list)
    """Findings whose category matches the AI's category."""
    unmatched_rule_ids: list[str] = field(default_factory=list)
    """Findings the AI's category does not cover."""
    rule_categories: list[str] = field(default_factory=list)
    ai_category: str = ""

    @property
    def is_conflict(self) -> bool:
        return self.status == "conflict"

    def warning(self) -> str | None:
        if self.status == "conflict":
            return (
                "AI / RULE CONFLICT — the AI's diagnosis does not correspond to any "
                "deterministic finding, at either the fault-category or the OSI-layer level. "
                "The rule engine inspected the actual configuration; the AI did not. "
                "Effective confidence has been capped at MEDIUM pending reviewer "
                "adjudication."
            )
        if self.status == "ai_only":
            return (
                "AI-ONLY DIAGNOSIS — the deterministic checker found no fault it can detect, "
                "so nothing corroborates this diagnosis. That may simply mean the fault is "
                "outside the rule catalogue, but the diagnosis is uncorroborated and "
                "confidence has been capped at MEDIUM."
            )
        if self.status == "rules_only":
            return (
                "RULES-ONLY — the deterministic checker found a fault that the AI did not "
                "identify. The rule findings are authoritative here and should drive the "
                "review."
            )
        if self.status == "partial":
            return (
                "PARTIAL AGREEMENT — the AI and the rule engine overlap but do not fully "
                "agree on the fault category. Review both before deciding."
            )
        return None


def reconcile(diagnosis: AIDiagnosis, findings: list[Finding]) -> ReconciliationResult:
    """Classify how the AI's diagnosis relates to the deterministic findings.

    Decision order (first match wins):

    * no findings, AI declined            -> ``agree``      (both say nothing is determinable)
    * no findings, AI asserted a cause    -> ``ai_only``    (uncorroborated)
    * findings exist, AI declined         -> ``rules_only`` (AI missed a detectable fault)
    * AI category matches a finding       -> ``agree``      (fully or partially, see below)
    * AI category differs, layer matches  -> ``partial``    (right area, wrong family)
    * neither matches                     -> ``conflict``
    """
    rule_categories = sorted({f.category.value for f in findings})
    ai_category = diagnosis.category

    if not findings:
        if not diagnosis.claims_a_root_cause():
            return ReconciliationResult(
                status="agree",
                reason=(
                    "The deterministic checker found no fault it can detect, and the AI "
                    "reported insufficient evidence. Both reached the same conclusion: "
                    "nothing is determinable from this evidence."
                ),
                ai_category=ai_category,
            )
        return ReconciliationResult(
            status="ai_only",
            reason=(
                f"The AI diagnosed a {ai_category} fault, but the deterministic checker "
                "found nothing. No rule finding corroborates this diagnosis."
            ),
            ai_category=ai_category,
        )

    all_rule_ids = sorted({f.rule_id for f in findings})

    if not diagnosis.claims_a_root_cause():
        return ReconciliationResult(
            status="rules_only",
            reason=(
                f"The deterministic checker reported {len(findings)} finding(s) "
                f"({', '.join(all_rule_ids)}), but the AI reported insufficient evidence and "
                "identified no root cause."
            ),
            unmatched_rule_ids=all_rule_ids,
            rule_categories=rule_categories,
            ai_category=ai_category,
        )

    matched = sorted({f.rule_id for f in findings if f.category.value == ai_category})
    unmatched = sorted({f.rule_id for f in findings if f.category.value != ai_category})

    if matched:
        if unmatched:
            return ReconciliationResult(
                status="agree",
                reason=(
                    f"The AI's {ai_category} diagnosis is corroborated by "
                    f"{', '.join(matched)}. {len(unmatched)} further finding(s) "
                    f"({', '.join(unmatched)}) fall outside that category and are most "
                    "likely consequences of the same underlying fault."
                ),
                matched_rule_ids=matched,
                unmatched_rule_ids=unmatched,
                rule_categories=rule_categories,
                ai_category=ai_category,
            )
        return ReconciliationResult(
            status="agree",
            reason=(
                f"The AI's {ai_category} diagnosis is corroborated by every deterministic "
                f"finding ({', '.join(matched)})."
            ),
            matched_rule_ids=matched,
            rule_categories=rule_categories,
            ai_category=ai_category,
        )

    # Category disagrees. A matching OSI layer still means the AI is looking in the right
    # place, which is materially different from being simply wrong.
    ai_layer = diagnosis.osi_layer
    layer_matches = sorted({f.rule_id for f in findings if f.osi_layer.value == ai_layer})

    if layer_matches:
        return ReconciliationResult(
            status="partial",
            reason=(
                f"The AI diagnosed a {ai_category} fault while the deterministic checker "
                f"reported {', '.join(rule_categories)}. The categories disagree, but "
                f"{', '.join(layer_matches)} share the AI's OSI layer ({ai_layer}), so both "
                "are pointing at the same part of the stack."
            ),
            unmatched_rule_ids=all_rule_ids,
            rule_categories=rule_categories,
            ai_category=ai_category,
        )

    return ReconciliationResult(
        status="conflict",
        reason=(
            f"The AI diagnosed a {ai_category} fault at {ai_layer}, but the deterministic "
            f"checker reported {', '.join(rule_categories)} findings "
            f"({', '.join(all_rule_ids)}) at different layers. Nothing in the AI's diagnosis "
            "corresponds to what the rule engine actually observed in the configuration."
        ),
        unmatched_rule_ids=all_rule_ids,
        rule_categories=rule_categories,
        ai_category=ai_category,
    )
