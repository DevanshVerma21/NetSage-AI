"""Build the Responsible-AI log from *genuine* human reviews.

Reads ``data/evaluation_results.json`` (what Gemini produced) and ``data/reviews.json`` (what
human reviewers actually decided, recorded through the existing review service) and writes:

* ``data/responsible_ai_log.json``
* ``docs/RESPONSIBLE_AI.md``

The AI's output and the human's correction are kept in separate, clearly labelled fields; the
correction never overwrites the proposal. The ``lesson`` field is derived mechanically from the
recorded facts and is labelled as such, so nothing in this file can be mistaken for a sentence
a reviewer did not write.

A correction means a review whose verdict is ``edited`` or ``rejected``. If fewer than five
exist, this script writes nothing and exits non-zero: the honest report is "the reviews have not
been done yet", and manufacturing an error to reach the threshold would corrupt the record.

Usage::

    python -m backend.scripts.build_responsible_ai
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backend.app.config import get_settings
from backend.app.models.records import DiagnosisRecord, ReviewRecord
from backend.app.services import diagnosis_repo, review_service
from backend.app.services.evaluation import EvaluationRecord
from backend.app.store import write_json
from backend.scripts.evaluate_all_cases import load_results

REQUIRED_CORRECTIONS = 5
CORRECTION_VERDICTS = review_service.CORRECTION_VERDICTS

LOG_FILE = "responsible_ai_log.json"
DOC_PATH = Path("docs/RESPONSIBLE_AI.md")


def corrections() -> list[ReviewRecord]:
    """Every genuine human correction on record, oldest first.

    Two filters, both deliberate, and both defined once in ``review_service`` so this script and
    the dashboard cannot disagree about the count. The verdict must be a correction — an
    ``accepted`` review is agreement, not a correction. And the diagnosis it corrects must be a
    real model output, so a reviewer working through mock-provider answers cannot move the
    counter.
    """
    return review_service.genuine_corrections()


def excluded_corrections() -> list[ReviewRecord]:
    """Corrections that are real reviews but not evidence about a model.

    Reported rather than dropped in silence: a reviewer who spent the effort should be told why
    their verdict did not count.
    """
    return review_service.synthetic_corrections()


def _lesson(review: ReviewRecord, evaluation: Optional[EvaluationRecord]) -> str:
    """Derive the lesson from what was recorded. Mechanical, never invented.

    Composed only from fields that already exist: the verdict, what the reviewer corrected, and
    the deterministic checks' verdicts on the same diagnosis.
    """
    parts: list[str] = []

    if review.verdict == "rejected":
        parts.append(
            "A reviewer rejected the AI's root cause outright, so the proposal was never "
            "eligible for a simulated fix."
        )
    else:
        corrected = [
            name
            for name, value in (
                ("root cause", review.corrected_root_cause),
                ("OSI layer", review.corrected_osi_layer),
                ("category", review.corrected_category),
                ("fix steps", review.corrected_fix_steps or None),
            )
            if value
        ]
        parts.append(
            "A reviewer kept the diagnosis but corrected "
            f"{', '.join(corrected) if corrected else 'part of it'}."
        )

    if evaluation is not None:
        if evaluation.evidence_integrity == "failed":
            parts.append(
                "The evidence verifier had already found that none of the AI's citations "
                "appeared in the supplied output, and confidence was capped at LOW before the "
                "reviewer saw it — the automated check and the human agreed."
            )
        elif evaluation.evidence_integrity == "partial":
            parts.append(
                f"{evaluation.failed_citations} of {evaluation.total_citations} citations "
                "could not be located in the supplied output, which is a signal that was "
                "visible before review."
            )
        if evaluation.reconciliation == "conflict":
            parts.append(
                "The deterministic rule engine had also contradicted the diagnosis "
                "(reconciliation = conflict)."
            )
        if (
            evaluation.model_confidence == "high"
            and evaluation.effective_confidence == "high"
        ):
            parts.append(
                "The model claimed HIGH confidence and no cap applied, so nothing automated "
                "flagged this one — the human review is the only thing that caught it. This is "
                "the failure mode the mandatory review gate exists for."
            )
        elif evaluation.confidence_was_capped:
            parts.append(
                f"Confidence had already been reduced from "
                f"{evaluation.model_confidence} to {evaluation.effective_confidence} by the "
                "deterministic caps."
            )

    if review.reason_code:
        parts.append(f"Reviewer reason code: {review.reason_code}.")

    return " ".join(parts)


def build_entries(
    reviews: list[ReviewRecord],
    evaluations: dict[str, EvaluationRecord],
) -> list[dict]:
    entries: list[dict] = []
    for review in reviews:
        diagnosis: Optional[DiagnosisRecord] = diagnosis_repo.get(review.diagnosis_id)
        evaluation = evaluations.get((review.case_id or "").upper())

        ai_block = {
            "root_cause": diagnosis.ai.root_cause if diagnosis else None,
            "osi_layer": diagnosis.ai.osi_layer if diagnosis else None,
            "category": diagnosis.ai.category if diagnosis else None,
            "next_command": diagnosis.ai.next_command if diagnosis else None,
            "fix_steps": evaluation.fix_steps if evaluation else [],
            "provider": evaluation.provider if evaluation else None,
            "model": evaluation.model if evaluation else None,
        }

        entries.append(
            {
                "case_id": review.case_id,
                "diagnosis_id": review.diagnosis_id,
                "review_id": review.review_id,
                # --- what the AI said -------------------------------------------------
                "ai_diagnosis": ai_block,
                "model_confidence": evaluation.model_confidence if evaluation else None,
                "effective_confidence": (
                    evaluation.effective_confidence if evaluation else None
                ),
                "evidence": [
                    citation.model_dump(mode="json")
                    for citation in (evaluation.ai_evidence if evaluation else [])
                ],
                "evidence_integrity": evaluation.evidence_integrity if evaluation else None,
                "reconciliation": evaluation.reconciliation if evaluation else None,
                "evaluation_result": evaluation.evaluation_result if evaluation else None,
                # --- what the human decided -------------------------------------------
                "human_decision": review.verdict,
                "reviewer": review.reviewer,
                "corrected_diagnosis": {
                    "root_cause": review.corrected_root_cause,
                    "osi_layer": review.corrected_osi_layer,
                    "category": review.corrected_category,
                    "fix_steps": list(review.corrected_fix_steps),
                },
                "reason_code": review.reason_code,
                "human_notes": review.notes,
                "human_agreement": review.agreement.model_dump(mode="json"),
                # --- derived, and labelled as derived ---------------------------------
                "lesson": _lesson(review, evaluation),
                "lesson_source": "derived from the stored review and the deterministic checks",
                "timestamp": review.created_at,
                "applied": bool(diagnosis.applied) if diagnosis else False,
            }
        )
    return entries


def build_payload(entries: list[dict]) -> dict:
    stats = review_service.agreement_stats()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "reviews": "data/reviews.json",
            "diagnoses": "data/diagnoses.json",
            "evaluation": "data/evaluation_results.json",
        },
        "note": (
            "Every human_decision, corrected_diagnosis, reason_code and human_notes value in "
            "this file was typed by a person through backend/scripts/review_candidates.py and "
            "stored by review_service. The 'lesson' field is derived mechanically from those "
            "records and the deterministic checks; it is not a reviewer's sentence."
        ),
        "review_totals": stats,
        "required_corrections": REQUIRED_CORRECTIONS,
        "total_corrections": len(entries),
        "corrections": entries,
    }


# --- markdown ------------------------------------------------------------------------------


def _fmt(value: object) -> str:
    if value is None or value == "" or value == []:
        return "_not recorded_"
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    return str(value)


def render_markdown(payload: dict) -> str:
    lines: list[str] = [
        "# Responsible AI — what humans corrected",
        "",
        "Generated by `python -m backend.scripts.build_responsible_ai` from "
        "`data/responsible_ai_log.json`. Do not edit by hand.",
        "",
        f"Generated at: {payload['generated_at']}",
        "",
        "## How to read this",
        "",
        "Each entry keeps three things apart:",
        "",
        "1. **What the AI produced** — Gemini's root cause, its own confidence, the confidence "
        "the deterministic caps actually allowed, and its citations with the verifier's verdict "
        "on each one.",
        "2. **What the human decided** — the verdict, the correction, the reason code and the "
        "reviewer's own notes, exactly as recorded. A correction never overwrites the AI's "
        "proposal; both are stored.",
        "3. **The lesson** — derived mechanically from (1) and (2). It is labelled "
        "`lesson_source` in the JSON so it cannot be mistaken for something a reviewer wrote.",
        "",
        "No diagnosis in this file was applied to a device. NetSage AI simulates fixes only, "
        "and `applied` stays false until a human runs the simulator explicitly.",
        "",
        "## Totals",
        "",
        "| Metric | Value |",
        "| --- | --- |",
    ]
    stats = payload["review_totals"]
    for key in ("total", "accepted", "edited", "rejected"):
        lines.append(f"| reviews {key} | {stats.get(key, 0)} |")
    lines += [
        f"| corrections documented (edited + rejected) | {payload['total_corrections']} |",
        f"| corrections required by the phase spec | {payload['required_corrections']} |",
        "",
        "## Corrections",
        "",
    ]

    for index, entry in enumerate(payload["corrections"], start=1):
        ai = entry["ai_diagnosis"]
        corrected = entry["corrected_diagnosis"]
        lines += [
            f"### {index}. {_fmt(entry['case_id'])} — human decision: "
            f"**{entry['human_decision'].upper()}**",
            "",
            f"- diagnosis: `{entry['diagnosis_id']}` · review: `{entry['review_id']}` · "
            f"recorded {entry['timestamp']}",
            f"- mechanical evaluation: {_fmt(entry['evaluation_result'])} · "
            f"evidence {_fmt(entry['evidence_integrity'])} · "
            f"reconciliation {_fmt(entry['reconciliation'])}",
            f"- confidence: model **{_fmt(entry['model_confidence'])}** → effective "
            f"**{_fmt(entry['effective_confidence'])}**",
            f"- applied to any device: **{'yes' if entry['applied'] else 'no'}**",
            "",
            "**AI proposal**",
            "",
            f"- root cause: {_fmt(ai['root_cause'])}",
            f"- category / OSI: {_fmt(ai['category'])} / {_fmt(ai['osi_layer'])}",
            f"- next command: {_fmt(ai['next_command'])}",
        ]
        for step in ai["fix_steps"]:
            lines.append(f"- proposed fix: {step}")
        lines += [
            f"- provider / model: {_fmt(ai['provider'])} / {_fmt(ai['model'])}",
            "",
        ]

        if entry["evidence"]:
            lines += [
                "**AI citations, as checked by the deterministic verifier**",
                "",
                "| # | source command | verified | excerpt | why it failed |",
                "| --- | --- | --- | --- | --- |",
            ]
            for number, citation in enumerate(entry["evidence"], start=1):
                excerpt = str(citation.get("excerpt") or "").replace("|", "\\|")
                excerpt = " ".join(excerpt.split())[:80]
                reason = citation.get("failure_reason") or "—"
                lines.append(
                    f"| {number} | `{citation.get('source_command') or '—'}` | "
                    f"{'yes' if citation.get('verified') else 'NO'} | {excerpt or '—'} | "
                    f"{reason} |"
                )
            lines.append("")
        else:
            lines += ["**AI citations**: none recorded.", ""]

        lines += [
            "**Human correction**",
            "",
            f"- reviewer: {_fmt(entry['reviewer'])}",
            f"- reason code: {_fmt(entry['reason_code'])}",
            f"- corrected root cause: {_fmt(corrected['root_cause'])}",
            f"- corrected category / OSI: {_fmt(corrected['category'])} / "
            f"{_fmt(corrected['osi_layer'])}",
            f"- corrected fix steps: {_fmt(corrected['fix_steps'])}",
            f"- reviewer notes: {_fmt(entry['human_notes'])}",
            "",
            f"**Lesson** _({entry['lesson_source']})_",
            "",
            entry["lesson"],
            "",
        ]

    return "\n".join(lines) + "\n"


# --- cli -----------------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--log-path", type=Path, default=None, help="override data/responsible_ai_log.json"
    )
    parser.add_argument(
        "--doc-path", type=Path, default=None, help="override docs/RESPONSIBLE_AI.md"
    )
    args = parser.parse_args(argv)

    reviews = corrections()
    if len(reviews) < REQUIRED_CORRECTIONS:
        stats = review_service.agreement_stats()
        excluded = excluded_corrections()
        note = ""
        if excluded:
            note = (
                f"\n{len(excluded)} correction(s) were excluded because the diagnosis they "
                "correct was not produced by a real provider call "
                f"({', '.join(sorted({r.diagnosis_id for r in excluded}))}). Correcting a "
                "mock-provider answer is not evidence about model behaviour.\n"
            )
        print(
            f"only {len(reviews)} genuine human correction(s) are on record "
            f"({stats['edited']} edited, {stats['rejected']} rejected out of {stats['total']} "
            f"review(s)); {REQUIRED_CORRECTIONS} are required.\n"
            f"{note}"
            "\nNothing was written. The Responsible-AI log must come from reviews a person "
            "actually performed, so the remaining corrections cannot be generated here.\n"
            "Run 'python -m backend.scripts.review_candidates' in an interactive terminal to "
            "review the queued candidates.",
            file=sys.stderr,
        )
        return 1

    evaluations = {record.case_id.upper(): record for record in load_results()}
    entries = build_entries(reviews, evaluations)
    payload = build_payload(entries)

    log_path = args.log_path or (get_settings().data_path / LOG_FILE)
    doc_path = args.doc_path or DOC_PATH
    write_json(log_path, payload)
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(render_markdown(payload), encoding="utf-8")

    print(f"{len(entries)} genuine correction(s) documented")
    print(f"  wrote {log_path}")
    print(f"  wrote {doc_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
