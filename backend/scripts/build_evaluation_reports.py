"""Build the Phase 6 evaluation reports and the human-review queue.

Reads ``data/evaluation_results.json`` and writes:

* ``reports/ai_evaluation.json``          — every metric, machine-readable
* ``reports/ai_evaluation.md``            — the same metrics, human-readable
* ``reports/case_evaluation_matrix.csv``  — exactly one row per evaluated case
* ``data/human_review_queue.json``        — review candidates, all ``status="pending"``

Makes no API calls and never touches ``data/cases.json``. Every number is calculated from the
stored results, so re-running it can only ever restate what Gemini actually produced.

Usage::

    python -m backend.scripts.build_evaluation_reports
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backend.app.config import get_settings
from backend.app.services.evaluation import (
    MATRIX_COLUMNS,
    compute_metrics,
    matrix_rows,
    render_markdown,
    select_review_candidates,
)
from backend.app.store import write_json
from backend.scripts.evaluate_all_cases import load_results

REPORTS_DIR = Path("reports")
QUEUE_FILE = "human_review_queue.json"


def write_matrix(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(MATRIX_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=None,
                        help="override the results file (default: data/evaluation_results.json)")
    args = parser.parse_args(argv)

    records = load_results(args.results)
    if not records:
        raise SystemExit(
            "no evaluation results found — run "
            "'python -m backend.scripts.evaluate_all_cases' first"
        )

    metrics = compute_metrics(records)
    rows = matrix_rows(records)
    candidates = select_review_candidates(records)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "data/evaluation_results.json",
        "methodology": "docs/evaluation_methodology.md",
        "metrics": metrics,
        "cases": rows,
    }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    write_json(REPORTS_DIR / "ai_evaluation.json", payload)
    (REPORTS_DIR / "ai_evaluation.md").write_text(
        render_markdown(metrics, records), encoding="utf-8"
    )
    write_matrix(rows, REPORTS_DIR / "case_evaluation_matrix.csv")

    queue_path = get_settings().data_path / QUEUE_FILE
    write_json(
        queue_path,
        {
            "generated_at": payload["generated_at"],
            "source": "data/evaluation_results.json",
            "selection_priority": [
                "1 INCORRECT",
                "2 PARTIAL",
                "3 evidence_integrity = failed",
                "4 reconciliation = conflict",
                "5 high-confidence INCORRECT/PARTIAL",
                "6 suspiciously unsupported diagnosis",
            ],
            "note": (
                "Candidates only. Every entry is status='pending'; no human decision is "
                "recorded here. Reviews are made with "
                "'python -m backend.scripts.review_candidates' and stored in "
                "data/reviews.json by the existing review service."
            ),
            "total_candidates": len(candidates),
            "candidates": candidates,
        },
    )

    print(f"cases evaluated      : {metrics['totals']['total_cases']}")
    print(f"  successful         : {metrics['totals']['successful']}")
    print(f"  failed             : {metrics['totals']['failed']}")
    for name, count in metrics["results"].items():
        print(f"  {name:<20}: {count}")
    print(f"matrix rows          : {len(rows)}")
    print(f"review candidates    : {len(candidates)}")
    print("\nwrote reports/ai_evaluation.json, reports/ai_evaluation.md, "
          f"reports/case_evaluation_matrix.csv and {queue_path}")
    if metrics["totals"]["failed"]:
        print(f"note: failed case(s) recorded: {', '.join(metrics['totals']['failed_case_ids'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
