"""Run one live Gemini diagnosis and print the full pipeline result.

    python -m backend.scripts.live_diagnose_demo
    python -m backend.scripts.live_diagnose_demo CASE-001

Skips cleanly with an explanatory message when GEMINI_API_KEY is not configured, so it is
safe to run on any checkout. The API key is never printed.
"""

from __future__ import annotations

import sys

from backend.app.ai.factory import build_provider
from backend.app.config import get_settings
from backend.app.services import case_repo
from backend.app.services.diagnose import diagnose_case

RULE = "=" * 78


def main(argv: list[str]) -> int:
    case_id = argv[1] if len(argv) > 1 else "CASE-001"
    settings = get_settings()

    if not settings.gemini_api_key:
        print("Live Gemini demo skipped — GEMINI_API_KEY not configured.")
        print("Copy .env.example to .env and add a free key from "
              "https://aistudio.google.com/apikey")
        print("The prototype remains fully usable offline with LLM_PROVIDER=mock.")
        return 0

    case_repo.clear_cache()
    case = case_repo.get_case(case_id, use_cache=False)
    if case is None:
        print(f"error: no such case: {case_id}")
        return 2

    print(RULE)
    print(f"LIVE GEMINI DIAGNOSIS — {case.case_id}")
    print(f"provider=gemini  model={settings.llm_model}")
    print(RULE)
    print(f"SYMPTOM: {case.symptom}\n")

    result = diagnose_case(case, provider=build_provider("gemini"))

    for line in result.summary_lines():
        print(f"  {line}")

    print(f"\n  Root cause (verbatim from the model):\n    {result.ai.root_cause}")

    print(f"\n  Evidence citations ({len(result.ai.evidence)}):")
    for index, item in enumerate(result.ai.evidence, start=1):
        verified = any(v.index == index - 1 for v in result.evidence_verification.verified_items)
        mark = "VERIFIED" if verified else "UNVERIFIED"
        print(f"    [{index}] {mark}  source_command: {item.source_command}")
        print(f"        excerpt: {item.excerpt}")
        print(f"        why    : {item.why_it_matters}")

    print(f"\n  Verification: {result.evidence_verification.details}")
    print(f"\n  Reconciliation ({result.agreement}): {result.reconciliation.reason}")
    print(f"\n  Confidence: {result.confidence.summary()}")

    print(f"\n  Next command: {result.ai.next_command}")

    print(f"\n  Proposed fix steps ({len(result.ai.fix_steps)}) — recommendations only:")
    for step in result.ai.fix_steps:
        print(f"    {step.order}. [{step.device}] risk={step.risk}")
        for command in step.cli_commands:
            print(f"         {command}")
        print(f"       rationale: {step.rationale}")

    print(f"\n  Alternative hypotheses ({len(result.ai.alternative_hypotheses)}):")
    for alt in result.ai.alternative_hypotheses:
        print(f"    - {alt.cause}")
        print(f"      less likely because: {alt.why_less_likely}")

    print(f"\n  Notes for reviewer:\n    {result.ai.notes_for_reviewer}")

    if result.token_usage:
        print(f"\n  Token usage: {result.token_usage}")
    print(f"  Latency: {result.latency_ms} ms")

    print()
    print(RULE)
    print(f"status={result.status}  applied={result.applied}")
    print("No fix has been applied or verified. Human review is required — Phase 3.")
    print(RULE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
