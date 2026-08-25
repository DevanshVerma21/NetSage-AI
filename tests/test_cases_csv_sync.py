"""Drift guard for the cases.csv deliverable.

``data/cases.csv`` is a graded company deliverable generated from ``data/cases.json``.
These tests fail if someone edits the JSON without regenerating the CSV, so the file a
grader opens can never disagree with the dataset the system actually runs on.
"""

from __future__ import annotations

import csv
import io

import pytest

from backend.app.models.enums import ConceptTag, OSILayer, Severity
from backend.app.services import case_repo
from backend.scripts.export_cases_csv import COLUMNS, output_path, render_csv


@pytest.fixture(scope="module")
def cases():
    case_repo.clear_cache()
    return case_repo.all_cases(use_cache=False)


def test_cases_csv_exists():
    assert output_path().exists(), (
        "data/cases.csv is missing — run: python -m backend.scripts.export_cases_csv"
    )


def test_committed_csv_matches_the_dataset(cases):
    committed = output_path().read_text(encoding="utf-8")
    regenerated = render_csv(cases)
    assert committed == regenerated, (
        "data/cases.csv is out of date — run: python -m backend.scripts.export_cases_csv"
    )


def test_csv_has_the_columns_the_document_requires():
    """The document's deliverable row: symptom, show outputs, expected fault,
    OSI layer, concept, severity."""
    required = {
        "symptom",
        "show_outputs",
        "expected_fault",
        "osi_layer",
        "concept_tag",
        "severity",
    }
    assert required.issubset(set(COLUMNS))


def test_csv_parses_and_row_count_matches(cases):
    text = output_path().read_text(encoding="utf-8")
    rows = list(csv.DictReader(io.StringIO(text)))
    assert len(rows) == len(cases)
    assert list(rows[0].keys()) == COLUMNS


def test_csv_cells_carry_real_values(cases):
    text = output_path().read_text(encoding="utf-8")
    rows = list(csv.DictReader(io.StringIO(text)))
    valid_layers = {layer.value for layer in OSILayer}
    valid_severities = {sev.value for sev in Severity}
    valid_concepts = {tag.value for tag in ConceptTag}

    for row in rows:
        assert row["symptom"].strip()
        assert row["expected_fault"].strip()
        assert row["osi_layer"] in valid_layers
        assert row["severity"] in valid_severities
        assert row["concept_tag"] in valid_concepts
        assert row["source_label"] == "simulated-lab"


def test_csv_embeds_the_actual_show_command_evidence(cases):
    """A grader must be able to read the evidence from the CSV itself."""
    text = output_path().read_text(encoding="utf-8")
    rows = {row["case_id"]: row for row in csv.DictReader(io.StringIO(text))}

    for case in cases:
        cell = rows[case.case_id]["show_outputs"]
        for entry in case.show_outputs:
            assert entry.command in cell, (
                f"{case.case_id}: command '{entry.command}' missing from the CSV cell"
            )
