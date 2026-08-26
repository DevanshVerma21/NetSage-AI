"""Interactive human review of the Phase 6 evaluation candidates.

This tool exists so the human-review requirement can be satisfied *genuinely*. It presents one
candidate at a time — the AI's diagnosis beside the stored ground truth — and records whatever
verdict the person at the keyboard types, through the existing
:mod:`backend.app.services.review_service`. That service enforces the gate rules (an ``edited``
review must carry a correction and a reason code, a ``rejected`` review must carry a reason code
and notes, one review per diagnosis, no overwriting).

Deliberate properties:

* **No decision is generated here.** Every verdict comes from stdin. There is no flag, default
  or batch mode that records a verdict without a human typing it.
* **Refuses to run without a terminal.** A non-interactive stdin exits with an error rather
  than falling back to an assumed answer, so no automated run can manufacture reviews.
* **Never applies anything.** Reviewing sets the diagnosis status only; ``applied`` stays false
  and a fix still requires the separate simulator.

Usage::

    python -m backend.scripts.review_candidates --list     # show the queue, decide nothing
    python -m backend.scripts.review_candidates            # review pending candidates
    python -m backend.scripts.review_candidates --case CASE-013
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from backend.app.config import get_settings
from backend.app.services import review_service
from backend.app.services.errors import ConflictError, NotFoundError, ValidationError
from backend.app.store import read_json

QUEUE_FILE = "human_review_queue.json"

VERDICT_KEYS = {
    "a": "accepted",
    "e": "edited",
    "r": "rejected",
}


def queue_path() -> Path:
    return get_settings().data_path / QUEUE_FILE


def load_queue(path: Optional[Path] = None) -> list[dict]:
    payload = read_json(path or queue_path(), default=None)
    if not payload:
        raise SystemExit(
            f"no review queue at {path or queue_path()} — run "
            "'python -m backend.scripts.build_evaluation_reports' first"
        )
    return list(payload.get("candidates", []))


def already_reviewed(candidate: dict) -> Optional[str]:
    """The existing verdict for this candidate's diagnosis, if a human already decided."""
    diagnosis_id = candidate.get("diagnosis_id")
    if not diagnosis_id:
        return None
    existing = review_service.for_diagnosis(diagnosis_id)
    return existing.verdict if existing else None


# --- presentation --------------------------------------------------------------------------


def show(candidate: dict, index: int, total: int) -> None:
    ai = candidate["ai_diagnosis"]
    expected = candidate["expected_diagnosis"]

    print("\n" + "=" * 78)
    print(f"[{index}/{total}] {candidate['case_id']}   "
          f"evaluation={candidate['evaluation_result']}   "
          f"priority={candidate['priority']} ({candidate['priority_label']})")
    print("=" * 78)

    print("\n-- AI proposal " + "-" * 62)
    print(f"root cause      : {ai['root_cause']}")
    print(f"category / OSI  : {ai['category']} / {ai['osi_layer']}")
    print(f"next command    : {ai['next_command']}")
    for step in ai.get("fix_steps") or []:
        print(f"fix             : {step}")
    print(f"confidence      : model={candidate['model_confidence']} "
          f"-> effective={candidate['effective_confidence']}")
    print(f"evidence        : {candidate['evidence_integrity']}")
    print(f"reconciliation  : {candidate['reconciliation']}")

    print("\n-- Ground truth (data/cases.json) " + "-" * 43)
    print(f"expected fault  : {expected['expected_fault']}")
    print(f"category / OSI  : {expected['category']} / {expected['osi_layer']}")
    print(f"expected rules  : {', '.join(expected['expected_rule_ids']) or 'none'}")
    print(f"keywords        : {', '.join(expected['expected_root_cause_keywords'])}")

    print("\n-- Why this case is queued " + "-" * 50)
    for reason in candidate["reason_for_review"]:
        print(f"  * {reason}")


def ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        raise SystemExit("\nstdin closed — no verdict was recorded")


def collect_verdict(candidate: dict) -> Optional[dict]:
    """Prompt for one human verdict. Returns None when the reviewer skips the case."""
    while True:
        answer = ask(
            "\nverdict — [a]ccepted / [e]dited / [r]ejected / [s]kip / [q]uit: "
        ).lower()

        if answer in ("q", "quit"):
            raise SystemExit("stopped by the reviewer")
        if answer in ("s", "skip", ""):
            return None
        if answer not in VERDICT_KEYS:
            print("  please answer a, e, r, s or q")
            continue

        verdict = VERDICT_KEYS[answer]
        payload: dict = {"verdict": verdict}

        reviewer = ask("reviewer name (blank = human-reviewer): ")
        if reviewer:
            payload["reviewer"] = reviewer

        if verdict == "edited":
            print("\nan edited review must record what the correct conclusion is")
            payload["corrected_root_cause"] = ask("corrected root cause: ")
            payload["corrected_osi_layer"] = ask(
                f"corrected OSI layer (blank keeps {candidate['ai_diagnosis']['osi_layer']}): "
            ) or None
            payload["corrected_category"] = ask(
                f"corrected category (blank keeps {candidate['ai_diagnosis']['category']}): "
            ) or None
            steps = ask("corrected fix steps (semicolon separated, optional): ")
            payload["corrected_fix_steps"] = [
                step.strip() for step in steps.split(";") if step.strip()
            ]
            payload["reason_code"] = ask("reason code (e.g. wrong_root_cause): ")
            payload["notes"] = ask("notes: ") or None

        elif verdict == "rejected":
            print("\na rejected review must record a reason code and notes")
            payload["reason_code"] = ask("reason code (e.g. unsupported_evidence): ")
            payload["notes"] = ask("notes: ")

        else:
            payload["reason_code"] = ask("reason code (optional): ") or None
            payload["notes"] = ask("notes (optional): ") or None

        return payload


# --- recording -----------------------------------------------------------------------------


def submit(candidate: dict, payload: dict) -> Optional[str]:
    """Persist one genuine verdict through the existing review service."""
    diagnosis_id = candidate.get("diagnosis_id")
    if not diagnosis_id:
        print("  ! this candidate has no stored diagnosis, so no review can be attached")
        return None
    try:
        review = review_service.create_review(diagnosis_id=diagnosis_id, **payload)
    except (ValidationError, ConflictError, NotFoundError) as exc:
        print(f"  ! rejected by the review gate: {exc}")
        return None
    print(f"  recorded {review.verdict} as {review.review_id}")
    return review.review_id


def summarise() -> None:
    stats = review_service.agreement_stats()
    corrections = stats["edited"] + stats["rejected"]
    print("\nreviews stored so far")
    for key in ("total", "accepted", "edited", "rejected"):
        print(f"  {key:<10}: {stats[key]}")
    print(f"  corrections (edited + rejected): {corrections}")
    if corrections < 5:
        print(f"\n  {5 - corrections} more genuine correction(s) are needed before "
              "'python -m backend.scripts.build_responsible_ai' will produce a log.")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true",
                        help="print the queue and the current review status; decide nothing")
    parser.add_argument("--case", help="review only this case id")
    args = parser.parse_args(argv)

    candidates = load_queue()
    if args.case:
        wanted = args.case.strip().upper()
        candidates = [c for c in candidates if c["case_id"].upper() == wanted]
        if not candidates:
            raise SystemExit(f"{args.case} is not in the review queue")

    if args.list:
        print(f"{len(candidates)} candidate(s) in the queue\n")
        header = f"{'case':<10} {'result':<20} {'pri':<4} {'reviewed':<10} reasons"
        print(header)
        print("-" * len(header))
        for candidate in candidates:
            verdict = already_reviewed(candidate) or "-"
            print(f"{candidate['case_id']:<10} {candidate['evaluation_result']:<20} "
                  f"{candidate['priority']:<4} {verdict:<10} "
                  f"{len(candidate['reason_for_review'])}")
        summarise()
        return 0

    if not sys.stdin.isatty():
        raise SystemExit(
            "refusing to run without an interactive terminal: every verdict must be typed by "
            "a human. Use --list to inspect the queue non-interactively."
        )

    outstanding = [c for c in candidates if already_reviewed(c) is None]
    print(f"{len(outstanding)} candidate(s) awaiting a human verdict "
          f"({len(candidates) - len(outstanding)} already reviewed)")

    for index, candidate in enumerate(outstanding, start=1):
        show(candidate, index, len(outstanding))
        payload = collect_verdict(candidate)
        if payload is None:
            print("  skipped — left pending")
            continue
        submit(candidate, payload)

    summarise()
    return 0


if __name__ == "__main__":
    sys.exit(main())
