"""The golden test: the rule engine and the dataset must agree.

This is the single most important test in the suite. It validates *both* directions at
once — a rule that stops working and a case whose declared ground truth is wrong both
fail here — and it is the mechanism behind the company document's grading check
"Python checker catches basic config errors correctly".
"""

from __future__ import annotations

import pytest

from backend.app.rules.engine import run_rules
from backend.app.services import case_repo


@pytest.fixture(scope="module")
def cases():
    case_repo.clear_cache()
    return case_repo.all_cases(use_cache=False)


def fired_rule_ids(case) -> list[str]:
    findings = run_rules(case.lab_state, case.intended_flows)
    return sorted({f.rule_id for f in findings})


def test_every_case_fires_exactly_its_expected_rules(cases):
    """Exact match, both directions: no missing detections, no spurious extras."""
    problems: list[str] = []

    for case in cases:
        expected = sorted(set(case.expected_rule_ids))
        fired = fired_rule_ids(case)
        if fired == expected:
            continue
        missing = [r for r in expected if r not in fired]
        extra = [r for r in fired if r not in expected]
        detail = f"{case.case_id}: expected={expected} fired={fired}"
        if missing:
            detail += f" MISSING={missing}"
        if extra:
            detail += f" EXTRA={extra}"
        problems.append(detail)

    assert not problems, "engine/dataset disagreement:\n  " + "\n  ".join(problems)


def test_every_finding_carries_usable_evidence(cases):
    """A finding with no evidence is not actionable by a human reviewer."""
    for case in cases:
        for finding in run_rules(case.lab_state, case.intended_flows):
            assert finding.evidence, (
                f"{case.case_id}/{finding.rule_id}: finding has no evidence"
            )
            for item in finding.evidence:
                assert item.source.strip()
                assert item.detail.strip()


def test_every_finding_is_deterministic_not_a_guess(cases):
    for case in cases:
        for finding in run_rules(case.lab_state, case.intended_flows):
            assert finding.confidence == "deterministic", (
                f"{case.case_id}/{finding.rule_id}: unexpected confidence "
                f"'{finding.confidence}' — engine errors must not appear in the dataset"
            )


def test_engine_is_repeatable(cases):
    """Same input, same output, same order — golden tests and CLI output depend on it."""
    for case in cases:
        first = run_rules(case.lab_state, case.intended_flows)
        second = run_rules(case.lab_state, case.intended_flows)
        assert [f.model_dump() for f in first] == [f.model_dump() for f in second]


def test_engine_does_not_mutate_the_lab_state(cases):
    """Rules must be pure — the Fix Simulator relies on the original state being intact."""
    for case in cases:
        before = case.lab_state.model_dump_json()
        run_rules(case.lab_state, case.intended_flows)
        assert case.lab_state.model_dump_json() == before, (
            f"{case.case_id}: a rule mutated the lab state"
        )
