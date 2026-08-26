"""Dashboard and Responsible-AI metrics, calculated from stored data on every request.

Nothing in this module is hard-coded. "40 cases" is `len(case_repo.all_cases())`, "15 rules"
is `len(registry())`, and every AI figure is derived from `data/evaluation_results.json`. Pass
an empty dataset and the dashboard truthfully reports zeros.

Two boundaries this module is careful about, because Phase 6 is quota-blocked and a dashboard
is exactly where an incomplete evaluation gets quietly rounded up to a headline:

* **Deterministic and AI figures never mix.** The rule engine ran on all 40 cases offline;
  the model has not. They are returned as two separate blocks with their own denominators.
* **Coverage is reported before accuracy.** `ai_evaluation` carries `evaluated`, `total`,
  `remaining` and a `status`, and `accuracy` is `None` until coverage is complete — so no
  caller can render "40-case accuracy" from a 1-case sample.

An `invalidated` record (produced under a prompt contract later found defective) counts as
*not evaluated*: it stays in the file for auditability but is never an official result.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from backend.app.rules.engine import mandatory_rule_ids, registry, run_rules
from backend.app.services import case_repo, review_service
from backend.app.services.evaluation import EvaluationRecord, compute_metrics
from backend.app.store import read_json
from backend.app.config import get_settings

RESULTS_FILE = "evaluation_results.json"
RESPONSIBLE_AI_LOG = "responsible_ai_log.json"

#: §12 of the phase brief: the Responsible AI requirement needs at least this many genuine
#: human corrections. Below it, the page shows an empty state rather than a thin sample.
REQUIRED_CORRECTIONS = 5

CORRECTION_VERDICTS = ("edited", "rejected")


def _data_path(filename: str) -> Path:
    return get_settings().data_path / filename


def load_evaluation_records(path: Optional[Path] = None) -> list[EvaluationRecord]:
    """Read the checkpoint file. A missing or malformed file yields no records, never an
    exception — the dashboard's job is to report that the evaluation has not run."""
    try:
        raw = read_json(path or _data_path(RESULTS_FILE), default=[])
    except Exception:
        # A truncated or hand-edited results file must not take the dashboard down with it.
        # Reporting zero evaluated cases is both safe and true: nothing readable is stored.
        return []
    if not isinstance(raw, list):
        return []
    records: list[EvaluationRecord] = []
    for entry in raw:
        try:
            records.append(EvaluationRecord.model_validate(entry))
        except Exception:
            continue
    return records


# --- the deterministic half ---------------------------------------------------------------


def deterministic_summary() -> dict:
    """The rule engine's own scorecard. No AI, no provider, no network call.

    ``golden_case_result`` is the expected-vs-fired comparison run live here rather than read
    from a test log, so the dashboard cannot claim a pass that the engine would not reproduce.
    """
    cases = case_repo.all_cases()
    rules = registry()
    mandatory = mandatory_rule_ids()
    optional = [rid for rid in rules if rid not in set(mandatory)]

    matched: list[str] = []
    mismatched: list[dict] = []
    for case in cases:
        expected = sorted(set(case.expected_rule_ids))
        fired = sorted({f.rule_id for f in run_rules(case.lab_state, case.intended_flows)})
        if fired == expected:
            matched.append(case.case_id)
        else:
            mismatched.append(
                {
                    "case_id": case.case_id,
                    "expected": expected,
                    "fired": fired,
                    "missing": [r for r in expected if r not in fired],
                    "extra": [r for r in fired if r not in expected],
                }
            )

    total = len(cases)
    return {
        "total_cases": total,
        "mandatory_rules": len(mandatory),
        "optional_rules": len(optional),
        "total_rules": len(rules),
        "mandatory_rule_ids": mandatory,
        "optional_rule_ids": sorted(optional),
        "rule_pass_rate": round(len(matched) / total, 4) if total else 0.0,
        "cases_matching_expected_rules": len(matched),
        "cases_not_matching": len(mismatched),
        "mismatches": mismatched,
        "golden_case_result": "PASS" if total and not mismatched else
                              ("FAIL" if mismatched else "NO DATA"),
        "golden_case_detail": (
            f"All {total} cases fire exactly their expected rule ids."
            if total and not mismatched
            else f"{len(mismatched)} of {total} cases disagree with the engine."
            if mismatched
            else "No cases are loaded."
        ),
        "verified_against": "simulated lab model",
    }


# --- the AI half --------------------------------------------------------------------------


def ai_evaluation_summary(records: Optional[list[EvaluationRecord]] = None) -> dict:
    """Coverage first, then only the figures the coverage supports.

    ``accuracy`` is ``None`` whenever coverage is incomplete. That is the whole point: with
    1 of 40 cases evaluated there is no such thing as a 40-case accuracy, and a caller that
    wants a percentage has to deal with the ``None``.
    """
    records = load_evaluation_records() if records is None else records
    total_cases = len(case_repo.all_cases())

    official = [r for r in records if r.is_official]
    invalidated = [r for r in records if r.invalidated]
    failed = [r for r in records if not r.succeeded]

    evaluated = len(official)
    remaining = max(total_cases - evaluated, 0)
    complete = total_cases > 0 and remaining == 0

    if evaluated == 0:
        # Distinguish "never run" from "run, but nothing survived as official". Both report
        # zero evaluated cases; only the second one has a quota story behind it.
        attempted = bool(records)
        status = "NOT_STARTED — Gemini quota limited" if attempted else "NOT_STARTED"
        headline = (
            f"No case has an official AI evaluation yet. {len(records)} attempt(s) are stored: "
            f"{len(failed)} failed on the Gemini free-tier daily quota and "
            f"{len(invalidated)} completed under a prompt contract since found defective and "
            "were invalidated. Nothing was substituted for the missing results."
            if attempted
            else "AI evaluation has not been run. No model result is stored."
        )
    elif complete:
        status = "COMPLETE"
        headline = f"All {total_cases} cases evaluated."
    else:
        status = "PARTIAL — Gemini quota limited"
        headline = (
            f"{evaluated} of {total_cases} cases evaluated. "
            f"{remaining} remaining. The Gemini free tier caps this project at 20 requests "
            "per day, which stopped the batch; the rest are unevaluated, not passed."
        )

    # compute_metrics is the Phase 6 metric function and is reused unchanged. It is given the
    # official records only, so an invalidated row cannot enter an accuracy denominator.
    metrics = compute_metrics(official)

    return {
        "evaluated": evaluated,
        "total": total_cases,
        "remaining": remaining,
        "pending": remaining,
        "status": status,
        "coverage_complete": complete,
        "headline": headline,
        "coverage_rate": round(evaluated / total_cases, 4) if total_cases else 0.0,
        # Present for auditability, deliberately outside the official counts.
        "stored_records": len(records),
        "failed_calls": len(failed),
        "failed_case_ids": [r.case_id for r in failed],
        "invalidated": len(invalidated),
        "invalidated_case_ids": [r.case_id for r in invalidated],
        "requires_rerun_case_ids": [r.case_id for r in records if r.requires_rerun],
        # Real stored outcomes. Every count below has `evaluated` as its denominator.
        "results": metrics["results"],
        "evidence": metrics["evidence"],
        "confidence": metrics["confidence"],
        "reconciliation": metrics["reconciliation"],
        "agreement": metrics["agreement"],
        "by_category": metrics["by_category"],
        "latency_ms": metrics["latency_ms"],
        "providers": metrics["providers"],
        "models": metrics["models"],
        "prompt_versions": metrics["prompt_versions"],
        # None until coverage is complete — see the docstring.
        "accuracy": metrics["accuracy"] if complete else None,
        "accuracy_note": (
            "Calculated over all evaluated cases."
            if complete
            else "Withheld: accuracy over an incomplete sample would not describe the "
                 "40-case dataset. The per-result counts above are real and are out of "
                 f"{evaluated} evaluated case(s)."
        ),
    }


def human_review_summary() -> dict:
    """Counts from the stored review records. Never a target, always the actual total."""
    reviews = review_service.all_records()
    corrections = [r for r in reviews if r.verdict in CORRECTION_VERDICTS]
    stats = review_service.agreement_stats()

    return {
        "total_reviews": len(reviews),
        "accepted": sum(1 for r in reviews if r.verdict == "accepted"),
        "edited": sum(1 for r in reviews if r.verdict == "edited"),
        "rejected": sum(1 for r in reviews if r.verdict == "rejected"),
        "corrections": len(corrections),
        "required_corrections": REQUIRED_CORRECTIONS,
        "corrections_complete": len(corrections) >= REQUIRED_CORRECTIONS,
        "incomplete_message": (
            None
            if len(corrections) >= REQUIRED_CORRECTIONS
            else "Human review data incomplete"
        ),
        "agreement_stats": stats,
        "reviewed_case_ids": sorted({r.case_id for r in reviews if r.case_id}),
    }


def responsible_ai_log() -> dict:
    """Expose ``data/responsible_ai_log.json`` if a genuine one has been generated.

    ``backend/scripts/build_responsible_ai.py`` refuses to write the file below the
    correction threshold, so its absence is itself the honest answer and is reported as an
    empty state rather than filled with examples.
    """
    path = _data_path(RESPONSIBLE_AI_LOG)
    try:
        payload = read_json(path, default=None)
    except Exception:
        payload = None
    entries = []
    if isinstance(payload, dict) and isinstance(payload.get("corrections"), list):
        entries = payload["corrections"]

    return {
        "available": bool(entries),
        "generated_at": payload.get("generated_at") if isinstance(payload, dict) else None,
        "source": payload.get("source") if isinstance(payload, dict) else None,
        "note": payload.get("note") if isinstance(payload, dict) else None,
        "required_corrections": REQUIRED_CORRECTIONS,
        "total_corrections": len(entries),
        "corrections": entries,
        "empty_state": (
            None
            if entries
            else "No genuine human correction has been recorded yet, so this log is empty. "
                 "It is generated from stored review records by "
                 "`python -m backend.scripts.build_responsible_ai`, which refuses to write "
                 f"anything below {REQUIRED_CORRECTIONS} corrections. No example entries are "
                 "shown in its place."
        ),
    }


def dashboard() -> dict:
    """The single payload behind the dashboard page."""
    records = load_evaluation_records()
    return {
        "deterministic": deterministic_summary(),
        "ai_evaluation": ai_evaluation_summary(records),
        "human_review": human_review_summary(),
        "separation_note": (
            "Deterministic figures come from the rule engine run over every stored case. AI "
            "figures come only from stored model evaluations. The two are never combined into "
            "a single score."
        ),
    }


def responsible_ai() -> dict:
    """The single payload behind the Responsible AI page."""
    records = load_evaluation_records()
    ai = ai_evaluation_summary(records)
    review = human_review_summary()
    return {
        "ai_evaluation": ai,
        "human_review": review,
        "log": responsible_ai_log(),
        "methodology": _methodology(),
        "execution_scope": _execution_scope(),
        "limitations": _limitations(ai, review),
    }


# --- disclosures --------------------------------------------------------------------------
#
# The prose below is a fixed description of how the system works, which is why it is a
# constant rather than a metric. Every *number* the page shows comes from the blocks above.


def _methodology() -> dict:
    from backend.app.ai.prompt_loader import load_registry

    try:
        prompts = load_registry().get("prompts", {})
    except Exception:
        prompts = {}

    return {
        "pipeline": [
            "The deterministic rule engine inspects the simulated lab state and produces its "
            "findings first, without any model involvement.",
            "The model receives the symptom, the topology note, the supplied show output and "
            "the rule findings. It never receives the case's expected answer.",
            "The model returns one structured proposal: root cause, OSI layer, category, "
            "cited evidence, a next command, and recommended fix steps.",
            "A deterministic verifier checks every citation against the supplied output.",
            "A reconciler compares the model's conclusion with the rule findings.",
            "Confidence capping reduces the model's own confidence when the checks do not "
            "support it. The model cannot raise its own effective confidence.",
            "The result is stored awaiting_human_review with applied=false. Only a human "
            "verdict can move it further.",
        ],
        "grading": [
            "Rule agreement — did the diagnosis cover the expected rule ids?",
            "Root-cause keyword agreement — against the case's stored keywords.",
            "OSI layer agreement.",
            "Category agreement.",
            "The four combine into CORRECT, PARTIAL, INCORRECT or UNABLE_TO_EVALUATE.",
        ],
        "grading_note": (
            "The model is never asked to grade itself, and the stored ground truth is never "
            "adjusted after seeing a model answer."
        ),
        "evidence_verification": {
            "rule": "Each excerpt must be a contiguous substring of the output of the command "
                    "named in source_command, and source_command must be one of the supplied "
                    "command strings.",
            "normalisation": "Runs of whitespace are collapsed and case is folded. Nothing "
                             "else. A paraphrase, a summary, stitched text, an added "
                             "annotation or an invented line does not verify.",
            "on_failure": "A failed citation is kept exactly as the model wrote it and shown "
                          "to the reviewer. It is never repaired, rewritten or hidden.",
            "statuses": ["passed", "partial", "failed"],
        },
        "confidence_capping": {
            "rule": "Effective confidence is the model's confidence after the deterministic "
                    "checks have been applied. It can only go down.",
            "triggers": [
                "Evidence integrity failed — capped at LOW.",
                "Evidence integrity partial — capped at MEDIUM.",
                "The model declared insufficient evidence — capped at LOW.",
                "The reconciler found a conflict with the rule findings.",
                "HIGH requires corroborating verified evidence, not assertion.",
            ],
        },
        "human_review": {
            "mandatory": True,
            "rule": "Every diagnosis is stored awaiting_human_review with applied=false. No "
                    "API parameter, provider or prompt can produce an already-approved or "
                    "already-applied result.",
            "verdicts": ["accepted", "edited", "rejected"],
            "gate": "A fix can only be simulated from a stored review. A rejected diagnosis "
                    "cannot be applied.",
        },
        "prompts": {
            name: {"version": entry.get("version"), "sha256": entry.get("sha256")}
            for name, entry in prompts.items()
        },
        "prompt_note": (
            "Every stored diagnosis records the name, version and SHA-256 of the exact "
            "instruction text that produced it, so a result can be traced to its prompt."
        ),
    }


def _execution_scope() -> dict:
    from backend.app.models.records import EXECUTION_SCOPE

    return {
        "scope": EXECUTION_SCOPE,
        "can": [
            "Read the supplied show output of a stored case.",
            "Propose a root cause, cited evidence and recommended fix steps.",
            "Simulate an approved fix against a copy of the in-memory lab model.",
            "Re-run the deterministic rules against that simulated result.",
        ],
        "cannot": [
            "Connect to any device. There is no SSH, Telnet or Netmiko code in this system.",
            "Execute a Cisco command anywhere, on hardware or in Packet Tracer.",
            "Apply, stage, schedule or roll back a real configuration change.",
            "Approve its own output, or bypass the human review gate.",
            "Accept a client-supplied mutation — a fix names a human approval, not a change.",
        ],
        "disclaimer": (
            "Every case is a simulated lab topology. Verification results describe the "
            "simulated model only, never physical hardware or Packet Tracer."
        ),
    }


def _limitations(ai: dict, review: dict) -> list[dict]:
    """Known limitations, with the honest ones stated first and their real numbers filled in."""
    items: list[dict] = []

    if not ai["coverage_complete"]:
        items.append(
            {
                "title": "AI evaluation is incomplete",
                "severity": "high",
                "detail": (
                    f"{ai['evaluated']} of {ai['total']} cases have an official evaluation; "
                    f"{ai['remaining']} remain. The Gemini free tier caps this project at 20 "
                    "requests per day per model, which stopped the batch. No figure on this "
                    "site describes the unevaluated cases, and no placeholder result was "
                    "generated for them."
                ),
            }
        )

    if ai["invalidated"]:
        items.append(
            {
                "title": "Some stored results were invalidated, not deleted",
                "severity": "medium",
                "detail": (
                    f"{ai['invalidated']} record(s) "
                    f"({', '.join(ai['invalidated_case_ids'])}) were produced under a prompt "
                    "contract later found defective. They are excluded from every official "
                    "figure but kept in the results file for auditability, and are marked "
                    "requires_rerun."
                ),
            }
        )

    if not review["corrections_complete"]:
        items.append(
            {
                "title": "Human review data incomplete",
                "severity": "high",
                "detail": (
                    f"{review['corrections']} genuine human correction(s) are stored; "
                    f"{review['required_corrections']} are required for the Responsible AI "
                    "log. Corrections must come from a person using the review workflow. "
                    "None were manufactured to close the gap."
                ),
            }
        )

    items.extend(
        [
            {
                "title": "Simulated lab, not a real network",
                "severity": "medium",
                "detail": (
                    "Cases are hand-built lab topologies with supplied show output. The "
                    "system has never been tested against live device output, which is "
                    "noisier, longer and less consistently formatted."
                ),
            },
            {
                "title": "Small, self-authored dataset",
                "severity": "medium",
                "detail": (
                    f"{ai['total']} cases, written alongside the rules they exercise. Ground "
                    "truth is a declared expectation, not an independently observed outcome, "
                    "so the golden test proves engine/dataset consistency rather than "
                    "real-world correctness."
                ),
            },
            {
                "title": "Rule coverage is bounded",
                "severity": "medium",
                "detail": (
                    "The engine implements a fixed set of rules. A fault outside them is not "
                    "detected deterministically, and the reconciler then has nothing to "
                    "corroborate the model against — which lowers confidence rather than "
                    "raising it."
                ),
            },
            {
                "title": "Verified citations are not a correctness guarantee",
                "severity": "medium",
                "detail": (
                    "The verifier proves an excerpt was really in the supplied output. It "
                    "cannot prove the excerpt supports the conclusion drawn from it. That "
                    "judgement is the reviewer's."
                ),
            },
            {
                "title": "Model output varies between runs",
                "severity": "low",
                "detail": (
                    "Even at low temperature the same case can produce differently worded "
                    "citations, so a single run is not a stable measurement of the model."
                ),
            },
            {
                "title": "No authentication or audit identity",
                "severity": "low",
                "detail": (
                    "Reviewer names are free text and there is no login. This is a prototype "
                    "and its review records would not stand up as an audit trail."
                ),
            },
        ]
    )
    return items

