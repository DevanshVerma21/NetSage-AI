"""Generate data/cases.csv from data/cases.json.

``cases.csv`` is a company deliverable, and its columns are exactly the ones the document
names: symptom, show outputs, expected fault, OSI layer, concept, severity.

The CSV is *generated*, never hand-edited. ``tests/test_cases_csv_sync.py`` fails if the
committed file drifts from the JSON, so the graded deliverable can never go stale.

    python -m backend.scripts.export_cases_csv
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from backend.app.config import get_settings
from backend.app.models.case import Case
from backend.app.services import case_repo

COLUMNS = [
    "case_id",
    "title",
    "symptom",
    "topology_note",
    "show_outputs",
    "expected_fault",
    "osi_layer",
    "concept_tag",
    "severity",
    "security_relevant",
    "expected_rule_ids",
    "expected_fix_steps",
    "source_label",
]


def _format_show_outputs(case: Case) -> str:
    """Flatten every show output into one cell, keeping device, command and text.

    A grader opening the CSV in a spreadsheet must be able to read the actual evidence,
    so the text is embedded rather than referenced.
    """
    blocks = [
        f"### {entry.device} :: {entry.command}\n{entry.output}" for entry in case.show_outputs
    ]
    return "\n\n".join(blocks)


def case_to_row(case: Case) -> dict[str, str]:
    return {
        "case_id": case.case_id,
        "title": case.title,
        "symptom": case.symptom,
        "topology_note": case.topology_note,
        "show_outputs": _format_show_outputs(case),
        "expected_fault": case.expected_fault,
        "osi_layer": case.osi_layer.value,
        "concept_tag": case.concept_tag.value,
        "severity": case.severity.value,
        "security_relevant": "yes" if case.security_relevant else "no",
        "expected_rule_ids": "; ".join(case.expected_rule_ids),
        "expected_fix_steps": "\n".join(
            f"{i}. {step}" for i, step in enumerate(case.expected_fix_steps, start=1)
        ),
        "source_label": case.source_label.value,
    }


def render_csv(cases: list[Case]) -> str:
    """Return the CSV text. Kept separate from file I/O so the sync test can compare
    the rendered output against the committed file without writing anything."""
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    for case in sorted(cases, key=lambda c: c.case_id):
        writer.writerow(case_to_row(case))
    return buffer.getvalue()


def output_path() -> Path:
    return get_settings().data_path / "cases.csv"


def main() -> int:
    cases = case_repo.all_cases(use_cache=False)
    if not cases:
        print("error: no cases to export")
        return 2

    target = output_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_csv(cases), encoding="utf-8", newline="")

    print(f"wrote {len(cases)} case(s) to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
