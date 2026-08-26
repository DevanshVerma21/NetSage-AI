"""Mark stored evaluation records as invalidated, without deleting evaluation history.

A record produced under a prompt contract that was later found defective is not an official
final result, but it is still evidence of what the model actually did — so it stays in
``data/evaluation_results.json`` and is stamped rather than removed.

    python -m backend.scripts.invalidate_evaluation_record --case CASE-001 \
        --reason "produced under diagnose_prompt v1.2.0, before the v1.2.1 source_command fix"

This script never calls a provider, never edits ground truth, and never changes any
evaluation metric. It sets three additive audit fields and rewrites the checkpoint file.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from backend.scripts.evaluate_all_cases import load_results, results_path, save_results


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, action="append", dest="cases",
                        help="case id to invalidate (repeatable)")
    parser.add_argument("--reason", required=True, help="why this record is not official")
    parser.add_argument("--undo", action="store_true", help="clear the invalidation instead")
    args = parser.parse_args(argv)

    wanted = {c.strip().upper() for c in args.cases}
    records = load_results()
    known = {r.case_id.upper() for r in records}

    missing = wanted - known
    if missing:
        print(f"error: no stored record for {', '.join(sorted(missing))}", file=sys.stderr)
        return 2

    touched = []
    for record in records:
        if record.case_id.upper() not in wanted:
            continue
        record.invalidated = not args.undo
        record.invalidated_reason = None if args.undo else args.reason
        record.requires_rerun = not args.undo
        touched.append(record)

    save_results(records)

    verb = "cleared" if args.undo else "invalidated"
    print(f"{verb} {len(touched)} record(s) in {results_path()}")
    for record in touched:
        print(f"  {record.case_id}: status={record.evaluation_status} "
              f"result={record.evaluation_result} prompt={record.prompt_version} "
              f"invalidated={record.invalidated} requires_rerun={record.requires_rerun}")
        if record.invalidated_reason:
            print(f"    reason: {record.invalidated_reason}")
    print(f"\n{len(records)} record(s) retained — nothing was deleted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
