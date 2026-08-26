"""Command-line deterministic rule checker.

This is the company document's "Python checker with sample output" deliverable. It runs
with no AI involvement and no network access whatsoever.

    python -m backend.app.rules.cli --case CASE-001
    python -m backend.app.rules.cli --all
    python -m backend.app.rules.cli --all --format table
    python -m backend.app.rules.cli --list-rules
    python -m backend.app.rules.cli --all --check-expected
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from backend.app.models.case import Case
from backend.app.rules.engine import Finding, mandatory_rule_ids, registry, run_rules
from backend.app.services import case_repo

SEP = "=" * 78
SUB = "-" * 78


def format_findings(case: Case, findings: list[Finding]) -> str:
    lines: list[str] = [
        SEP,
        f"{case.case_id}  {case.title}",
        f"  concept={case.concept_tag.value}  osi={case.osi_layer.value}  "
        f"severity={case.severity.value}  source={case.source_label.value}",
        SEP,
        f"SYMPTOM: {case.symptom}",
        "",
    ]

    if not findings:
        lines.append("No deterministic findings. (This does not prove the network is healthy —")
        lines.append("it means none of the implemented rules matched. See --list-rules.)")
        lines.append("")
        return "\n".join(lines)

    lines.append(f"DETERMINISTIC FINDINGS: {len(findings)}")
    lines.append("")
    for index, finding in enumerate(findings, start=1):
        lines.append(
            f"[{index}] {finding.rule_id} {finding.rule_name}  "
            f"({finding.severity.value} / {finding.osi_layer.value} / {finding.category.value})"
        )
        lines.append(f"    {finding.message}")
        for item in finding.evidence:
            lines.append(f"      evidence: {item.source} -> {item.detail}")
        if finding.affected:
            lines.append(f"      affected: {', '.join(finding.affected)}")
        if finding.suggested_check:
            lines.append(f"      confirm with: {finding.suggested_check}")
        lines.append("")

    return "\n".join(lines)


def format_expected_comparison(case: Case, findings: list[Finding]) -> str:
    """Compare fired rules with the case's declared expected_rule_ids."""
    fired = sorted({f.rule_id for f in findings})
    expected = sorted(set(case.expected_rule_ids))
    missing = [r for r in expected if r not in fired]
    extra = [r for r in fired if r not in expected]
    status = "PASS" if not missing and not extra else "FAIL"
    lines = [
        SUB,
        f"EXPECTED-FAULT CHECK: {status}",
        f"  expected: {', '.join(expected) or '(none)'}",
        f"  fired:    {', '.join(fired) or '(none)'}",
    ]
    if missing:
        lines.append(f"  MISSING:  {', '.join(missing)}")
    if extra:
        lines.append(f"  EXTRA:    {', '.join(extra)}")
    lines.append("")
    return "\n".join(lines)


def list_rules() -> str:
    mandatory = set(mandatory_rule_ids())
    lines = [
        SEP,
        "NETSAGE AI — DETERMINISTIC RULE CATALOGUE",
        SEP,
        f"{len(registry())} rules registered; {len(mandatory)} are mandatory per the "
        "company document.",
        "",
    ]
    for rule_id, meta in registry().items():
        flag = "MANDATORY" if rule_id in mandatory else "optional "
        lines.append(
            f"{rule_id}  [{flag}]  {meta.name}  "
            f"({meta.severity.value} / {meta.osi_layer.value} / {meta.category.value})"
        )
        lines.append(f"        {meta.description}")
        if meta.suggested_check:
            lines.append(f"        confirm with: {meta.suggested_check}")
        lines.append("")
    return "\n".join(lines)


def format_table(cases: list[Case], results: list[list[Finding]]) -> str:
    """A one-row-per-case summary: what was expected, what fired, and whether they agree.

    Used for the whole-dataset run, where 40 detailed reports are too long to read at once
    but the expected-versus-fired verdict for each case still has to be visible.
    """
    header = (
        f"{'CASE':<9} {'CATEGORY':<17} {'SEV':<9} {'OSI':<4} "
        f"{'EXPECTED':<22} {'FIRED':<22} RESULT"
    )
    lines = [
        SEP,
        "NETSAGE AI — DETERMINISTIC RULE CHECK, ALL CASES",
        SEP,
        f"cases: {len(cases)}   rules registered: {len(registry())}   "
        f"mandatory: {len(mandatory_rule_ids())}",
        "",
        header,
        SUB,
    ]

    failures: list[str] = []
    for case, findings in zip(cases, results):
        fired = sorted({f.rule_id for f in findings})
        expected = sorted(set(case.expected_rule_ids))
        ok = fired == expected
        if not ok:
            missing = ", ".join(r for r in expected if r not in fired) or "-"
            extra = ", ".join(r for r in fired if r not in expected) or "-"
            failures.append(f"{case.case_id}: MISSING {missing} / EXTRA {extra}")
        lines.append(
            f"{case.case_id:<9} {case.concept_tag.value:<17} {case.severity.value:<9} "
            f"{case.osi_layer.value:<4} {','.join(expected):<22} {','.join(fired):<22} "
            f"{'PASS' if ok else 'FAIL'}"
        )

    lines.extend(
        [
            SUB,
            f"total cases:      {len(cases)}",
            f"total rules:      {len(registry())} "
            f"({len(mandatory_rule_ids())} mandatory, "
            f"{len(registry()) - len(mandatory_rule_ids())} optional)",
            f"expected == fired: {len(cases) - len(failures)}/{len(cases)} cases",
            f"failures:         {len(failures)}",
        ]
    )
    for failure in failures:
        lines.append(f"  - {failure}")
    lines.append(SEP)
    return "\n".join(lines)


def run(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="netsage-rules",
        description="Deterministic Cisco lab configuration checker (no AI, no network).",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--case", help="Run the checker against one case id, e.g. CASE-001")
    group.add_argument("--all", action="store_true", help="Run against every case")
    group.add_argument("--list-rules", action="store_true", help="Print the rule catalogue")
    parser.add_argument(
        "--check-expected",
        action="store_true",
        help="Also compare fired rules against each case's expected_rule_ids",
    )
    parser.add_argument(
        "--format",
        choices=("detail", "table"),
        default="detail",
        help="detail = full findings per case (default); table = one summary row per case",
    )
    args = parser.parse_args(argv)

    if args.list_rules:
        print(list_rules())
        return 0

    if args.case:
        case = case_repo.get_case(args.case)
        if case is None:
            print(f"error: no such case: {args.case}", file=sys.stderr)
            return 2
        cases = [case]
    else:
        cases = case_repo.all_cases()
        if not cases:
            print("error: no cases found in the dataset", file=sys.stderr)
            return 2

    results = [run_rules(case.lab_state, case.intended_flows) for case in cases]

    # The table always states the expected-versus-fired verdict; that is the point of it.
    if args.format == "table":
        print(format_table(cases, results))
        return 1 if any(
            sorted({f.rule_id for f in findings}) != sorted(set(case.expected_rule_ids))
            for case, findings in zip(cases, results)
        ) else 0

    failures = 0
    for case, findings in zip(cases, results):
        print(format_findings(case, findings))
        if args.check_expected:
            comparison = format_expected_comparison(case, findings)
            print(comparison)
            if "FAIL" in comparison:
                failures += 1

    if args.check_expected:
        total = len(cases)
        print(SEP)
        print(f"SUMMARY: {total - failures}/{total} cases match their expected_rule_ids")
        print(SEP)
        return 1 if failures else 0

    return 0


if __name__ == "__main__":
    raise SystemExit(run())
