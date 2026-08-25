"""Deterministic evidence verification.

This module is the reason the system's evidence guarantee is real rather than aspirational.
The diagnosis prompt *asks* the model to cite verbatim from supplied output; this module
*checks* that it did. The model's claim carries no weight here — only the supplied text
does.

A failed citation is never silently dropped or repaired. It is recorded, surfaced to the
reviewer, and caps effective confidence at LOW.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, Optional

from backend.app.models.diagnosis import Evidence

VerificationStatus = Literal["passed", "partial", "failed"]

FailureReason = Literal[
    "excerpt_not_found",
    "unknown_source_command",
    "empty_excerpt",
]


def normalise(text: str) -> str:
    """Collapse whitespace so formatting differences do not cause false failures.

    A model that reflows a line, converts tabs to spaces, or loses trailing whitespace has
    still cited real evidence. A model that invented a line has not, and no amount of
    whitespace normalisation will make a fabricated address appear in the supplied text.
    Case is also folded: Cisco output casing is inconsistent and is not a fidelity signal.
    """
    return re.sub(r"\s+", " ", text).strip().lower()


@dataclass
class VerifiedItem:
    """One citation that was located in the supplied output."""

    index: int
    source_command: str
    excerpt: str
    matched_command: str
    """The supplied command whose output contained the excerpt."""


@dataclass
class FailedItem:
    """One citation that could not be substantiated."""

    index: int
    source_command: str
    excerpt: str
    reason: FailureReason
    detail: str


@dataclass
class EvidenceVerificationResult:
    status: VerificationStatus
    verified_items: list[VerifiedItem] = field(default_factory=list)
    failed_items: list[FailedItem] = field(default_factory=list)
    details: str = ""

    @property
    def verified_count(self) -> int:
        return len(self.verified_items)

    @property
    def failed_count(self) -> int:
        return len(self.failed_items)

    @property
    def total_count(self) -> int:
        return self.verified_count + self.failed_count

    @property
    def has_failures(self) -> bool:
        return bool(self.failed_items)

    def warning(self) -> Optional[str]:
        """Reviewer-facing warning, or None when everything checked out."""
        if self.status == "passed":
            return None
        if self.status == "failed":
            return (
                "EVIDENCE INTEGRITY FAILED — the AI cited evidence that does not appear in "
                "the supplied show-command output. Effective confidence has been capped at "
                "LOW. Treat this diagnosis with particular scepticism and verify every claim "
                "against the raw output before acting."
            )
        return (
            "EVIDENCE INTEGRITY PARTIAL — some of the AI's citations could not be located in "
            "the supplied output. The verified citations remain usable; the unverified ones "
            "are listed and should not be relied on."
        )


def verify_evidence(
    evidence: list[Evidence],
    corpus: dict[str, str],
    insufficient_evidence: bool = False,
) -> EvidenceVerificationResult:
    """Check every citation against the supplied output.

    Args:
        evidence: the model's citations.
        corpus: normalised-command -> supplied output text, from
            ``DiagnoseRequest.evidence_corpus()``.
        insufficient_evidence: whether the model declined to diagnose. An honest
            "I don't have enough evidence" with no citations is correct behaviour, not a
            verification failure.

    Status rules:
        * every citation located                -> ``passed``
        * some located, some not                -> ``partial``
        * none located, with at least one cited  -> ``failed``
        * nothing cited while declining          -> ``passed`` (nothing was claimed)
        * nothing cited while claiming a cause   -> ``failed`` (an unevidenced assertion)
    """
    if not evidence:
        if insufficient_evidence:
            return EvidenceVerificationResult(
                status="passed",
                details=(
                    "No citations to verify: the model reported insufficient evidence and "
                    "made no evidential claims."
                ),
            )
        return EvidenceVerificationResult(
            status="failed",
            details=(
                "The model asserted a root cause without citing any evidence. There is "
                "nothing to verify, so the assertion is unsupported."
            ),
        )

    # Both keys and values are normalised: the excerpt is normalised before comparison, so
    # the text it is compared against must be too, or every match would fail.
    normalised_corpus = {normalise(cmd): normalise(text) for cmd, text in corpus.items()}
    # Whole-corpus text, used to distinguish "wrong command" from "fabricated entirely".
    all_text = normalise("\n".join(corpus.values()))

    verified: list[VerifiedItem] = []
    failed: list[FailedItem] = []

    for index, item in enumerate(evidence):
        excerpt_norm = normalise(item.excerpt)
        command_norm = normalise(item.source_command)

        if not excerpt_norm:
            failed.append(
                FailedItem(
                    index=index,
                    source_command=item.source_command,
                    excerpt=item.excerpt,
                    reason="empty_excerpt",
                    detail="The citation's excerpt is empty after normalisation.",
                )
            )
            continue

        target = normalised_corpus.get(command_norm)

        if target is None:
            # The named command was never supplied. Report precisely which failure this is:
            # citing the wrong command is a different error from inventing the text.
            found_elsewhere = excerpt_norm in all_text
            available = ", ".join(sorted(corpus.keys())) or "(none)"
            detail = (
                f"'{item.source_command}' is not among the supplied commands ({available})."
            )
            detail += (
                " The excerpt text does appear in other supplied output, so this is a "
                "mis-attributed citation rather than a fabricated one."
                if found_elsewhere
                else " The excerpt does not appear in any supplied output either."
            )
            failed.append(
                FailedItem(
                    index=index,
                    source_command=item.source_command,
                    excerpt=item.excerpt,
                    reason="unknown_source_command",
                    detail=detail,
                )
            )
            continue

        if excerpt_norm in target:
            verified.append(
                VerifiedItem(
                    index=index,
                    source_command=item.source_command,
                    excerpt=item.excerpt,
                    matched_command=item.source_command,
                )
            )
            continue

        found_elsewhere = excerpt_norm in all_text
        detail = (
            f"The excerpt was not found in the output of '{item.source_command}'."
        )
        detail += (
            " It does appear in the output of a different supplied command, so the "
            "attribution is wrong."
            if found_elsewhere
            else " It does not appear anywhere in the supplied output."
        )
        failed.append(
            FailedItem(
                index=index,
                source_command=item.source_command,
                excerpt=item.excerpt,
                reason="excerpt_not_found",
                detail=detail,
            )
        )

    if not failed:
        status: VerificationStatus = "passed"
    elif not verified:
        status = "failed"
    else:
        status = "partial"

    return EvidenceVerificationResult(
        status=status,
        verified_items=verified,
        failed_items=failed,
        details=_summarise(status, verified, failed),
    )


def _summarise(
    status: VerificationStatus,
    verified: list[VerifiedItem],
    failed: list[FailedItem],
) -> str:
    total = len(verified) + len(failed)
    lines = [f"{len(verified)}/{total} citation(s) verified against the supplied output."]
    for item in failed:
        lines.append(
            f"  FAILED [{item.index}] ({item.reason}) "
            f"source_command='{item.source_command}' excerpt='{_truncate(item.excerpt)}' "
            f"-> {item.detail}"
        )
    if status == "passed" and verified:
        lines.append("  All citations located in the output of the command they name.")
    return "\n".join(lines)


def _truncate(text: str, limit: int = 80) -> str:
    single_line = " ".join(text.split())
    return single_line if len(single_line) <= limit else single_line[: limit - 1] + "…"
