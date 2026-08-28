"""Run the Phase 6 Gemini evaluation over the 40-case dataset.

One Gemini call per case, through the **existing** diagnosis pipeline — this script adds no
diagnosis logic of its own:

    case -> deterministic rules -> Gemini -> evidence verifier -> reconciler
         -> confidence capping -> evaluation record

Every successful case is checkpointed to ``data/evaluation_results.json`` immediately, so an
interrupted or rate-limited run resumes without repeating work or paying for it twice. A case
whose call permanently fails is *recorded as failed* and the run continues; no case is ever
silently dropped.

Usage::

    python -m backend.scripts.evaluate_all_cases --dry-run      # no API calls
    python -m backend.scripts.evaluate_all_cases                # full batch
    python -m backend.scripts.evaluate_all_cases --resume       # only the missing cases
    python -m backend.scripts.evaluate_all_cases --case CASE-007

The credential is read by ``Settings`` straight into the SDK client. It is never printed,
logged or written to any output file.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backend.app.ai.base import ProviderError
from backend.app.ai.gemini_provider import GeminiProvider
from backend.app.config import get_settings
from backend.app.models.case import Case
from backend.app.services import case_repo, diagnosis_repo
from backend.app.services.diagnose import diagnose_case
from backend.app.services.evaluation import (
    EvaluationRecord,
    failure_record,
    record_from_result,
)
from backend.app.store import read_json, write_json

RESULTS_FILE = "evaluation_results.json"


def results_path() -> Path:
    return get_settings().data_path / RESULTS_FILE


# --- checkpoint file ----------------------------------------------------------------------


def load_results(path: Optional[Path] = None) -> list[EvaluationRecord]:
    raw = read_json(path or results_path(), default=[])
    if not isinstance(raw, list):
        raise SystemExit(f"{path or results_path()} does not contain a JSON list")
    return [EvaluationRecord.model_validate(entry) for entry in raw]


def save_results(records: list[EvaluationRecord], path: Optional[Path] = None) -> None:
    """Write the whole file, ordered by case id so the checkpoint stays diffable."""
    ordered = sorted(records, key=lambda r: r.case_id)
    write_json(
        path or results_path(), [r.model_dump(mode="json") for r in ordered]
    )


def merge(existing: list[EvaluationRecord], new: EvaluationRecord) -> list[EvaluationRecord]:
    """Replace any earlier record for the same case. One row per case, always."""
    kept = [r for r in existing if r.case_id != new.case_id]
    kept.append(new)
    return kept


# --- pre-flight ---------------------------------------------------------------------------


def preflight(cases: list[Case]) -> GeminiProvider:
    """Verify the configuration before any quota is spent. Never echoes the key."""
    settings = get_settings()
    problems: list[str] = []

    if settings.llm_provider != "gemini":
        problems.append(
            f"LLM_PROVIDER is '{settings.llm_provider}', not 'gemini'. This evaluation must "
            "run against the live provider."
        )
    if not settings.llm_model:
        problems.append("LLM_MODEL is not configured.")
    if not settings.gemini_api_key:
        problems.append("GEMINI_API_KEY is not configured (checked for presence only).")
    if not cases:
        problems.append("no cases loaded from data/cases.json")

    if problems:
        for problem in problems:
            print(f"  FAIL  {problem}")
        raise SystemExit("pre-flight failed — no API calls were made")

    provider = GeminiProvider(settings=settings)
    if not provider.is_available():
        raise SystemExit("pre-flight failed — the Gemini provider reports unavailable")

    print(f"  ok    provider           : {settings.llm_provider}")
    print(f"  ok    model              : {settings.llm_model}")
    print("  ok    GEMINI_API_KEY      : present (value not shown)")
    print(f"  ok    cases loaded        : {len(cases)}")
    return provider


# --- the run ------------------------------------------------------------------------------


def evaluate_one(
    case: Case, provider: GeminiProvider, persist_diagnosis: bool = True
) -> EvaluationRecord:
    """One case, one Gemini call, through the existing pipeline.

    ``ProviderError`` is the pipeline's terminal failure: the provider has already applied its
    own bounded retry/backoff to transient 429/5xx conditions, so reaching this handler means
    the condition was not transient or the retries were exhausted. Retrying here would double
    the bound and spend quota for nothing.
    """
    try:
        result = diagnose_case(case, provider=provider)
    except ProviderError as exc:
        return failure_record(
            case,
            exc,
            attempts=1,
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            provider=provider.name,
            model=provider.model,
        )

    diagnosis_id: Optional[str] = None
    if persist_diagnosis:
        # Stored through the existing repository, so the record lands
        # awaiting_human_review with applied=False and the review gate stays intact.
        diagnosis_id = diagnosis_repo.save(result).diagnosis_id

    return record_from_result(case, result, diagnosis_id=diagnosis_id)


def run(
    cases: list[Case],
    provider: GeminiProvider,
    existing: list[EvaluationRecord],
    persist_diagnosis: bool = True,
) -> list[EvaluationRecord]:
    records = list(existing)
    total = len(cases)

    for index, case in enumerate(cases, start=1):
        print(f"[{index}/{total}] {case.case_id} ({case.concept_tag.value}) … ", end="",
              flush=True)
        record = evaluate_one(case, provider, persist_diagnosis=persist_diagnosis)
        records = merge(records, record)
        # Checkpoint after every case, successful or failed.
        save_results(records)

        if record.succeeded:
            print(
                f"{record.evaluation_result} "
                f"(conf {record.model_confidence}->{record.effective_confidence}, "
                f"evidence {record.evidence_integrity}, {record.reconciliation}, "
                f"{record.latency_ms} ms)"
            )
        else:
            print(f"FAILED — {record.error_type}: {record.error_message}")
            if "429" in (record.error_message or "") or "quota" in (record.error_message or "").lower():
                print("quota exhaustion detected — stopping immediately")
                break

    return records


# --- CLI -----------------------------------------------------------------------------------


def select_cases(all_cases: list[Case], case_id: Optional[str], resume: bool,
                 existing: list[EvaluationRecord]) -> list[Case]:
    cases = list(all_cases)

    if case_id:
        wanted = case_id.strip().upper()
        cases = [c for c in cases if c.case_id.upper() == wanted]
        if not cases:
            raise SystemExit(f"no such case: {case_id}")
        return cases

    if resume:
        # ``is_official`` rather than ``succeeded``: a record stamped invalidated because it
        # was produced under a superseded prompt contract still needs its live re-run, so it
        # must not be treated as done.
        done = {r.case_id for r in existing if r.is_official}
        cases = [c for c in cases if c.case_id not in done]

    return cases


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", action="store_true",
                        help="skip cases that already completed successfully")
    parser.add_argument("--case", help="evaluate only this case id")
    parser.add_argument("--dry-run", action="store_true",
                        help="validate the configuration and the work list; make no API calls")
    parser.add_argument("--no-persist-diagnosis", action="store_true",
                        help="do not write DiagnosisRecords (the human-review queue then has "
                             "no diagnosis to attach a review to)")
    args = parser.parse_args(argv)

    case_repo.clear_cache()
    all_cases = case_repo.all_cases(use_cache=False)

    print("pre-flight")
    provider = preflight(all_cases)

    existing = load_results()
    cases = select_cases(all_cases, args.case, args.resume, existing)

    print(f"  ok    already completed  : {sum(1 for r in existing if r.succeeded)}")
    print(f"  ok    to evaluate        : {len(cases)}")

    if args.dry_run:
        print("\ndry run — configuration validated, no API calls made")
        for case in cases:
            print(f"  would evaluate {case.case_id} ({case.concept_tag.value})")
        return 0

    if not cases:
        print("\nnothing to do")
        return 0

    print(f"\nevaluating {len(cases)} case(s) against {provider.model}\n")
    records = run(
        cases,
        provider=provider,
        existing=existing,
        persist_diagnosis=not args.no_persist_diagnosis,
    )

    succeeded = sum(1 for r in records if r.succeeded)
    failed = [r for r in records if not r.succeeded]
    print(f"\n{len(records)} record(s) stored in {results_path()}")
    print(f"  successful : {succeeded}")
    print(f"  failed     : {len(failed)}"
          + (f" ({', '.join(r.case_id for r in failed)})" if failed else ""))
    print("\nnext: python -m backend.scripts.build_evaluation_reports")
    return 0


if __name__ == "__main__":
    sys.exit(main())
