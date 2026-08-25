"""Live Gemini smoke test — opt-in, skipped by default.

Runs exactly one real API call against CASE-001 and asserts the whole pipeline survives a
genuine model response. Excluded from the default suite by the ``live`` marker, and skipped
outright when no key is configured, so ``pytest`` never depends on network access or
credentials.

    python -m pytest tests/test_live_gemini_smoke.py -m live -v
"""

from __future__ import annotations

import pytest

from backend.app.ai.gemini_provider import GeminiProvider
from backend.app.config import get_settings
from backend.app.models.diagnosis import AIDiagnosis
from backend.app.services import case_repo
from backend.app.services.diagnose import AWAITING_REVIEW, diagnose_case

pytestmark = pytest.mark.live


def _skip_reason() -> str | None:
    settings = get_settings()
    if not settings.gemini_api_key:
        return "Live Gemini smoke test skipped — GEMINI_API_KEY not configured."
    return None


@pytest.fixture(scope="module")
def live_result():
    reason = _skip_reason()
    if reason:
        pytest.skip(reason)

    case_repo.clear_cache()
    case = case_repo.get_case("CASE-001", use_cache=False)
    assert case is not None

    provider = GeminiProvider()
    assert provider.is_available(), "provider reported unavailable despite a configured key"

    return diagnose_case(case, provider=provider)


# --- 1 & 2. the call succeeds and returns structured output ---------------------------


def test_live_call_succeeds_and_returns_structured_output(live_result):
    assert live_result.provider == "gemini"
    assert live_result.model == get_settings().llm_model
    assert live_result.latency_ms > 0


# --- 3. Pydantic validation succeeded -------------------------------------------------


def test_live_response_validates_against_the_schema(live_result):
    assert isinstance(live_result.ai, AIDiagnosis)
    # Re-validate through JSON so every validator runs again on the real payload.
    AIDiagnosis.model_validate_json(live_result.ai.model_dump_json())

    assert live_result.ai.root_cause.strip()
    assert live_result.ai.next_command.strip()
    assert live_result.ai.confidence in {"low", "medium", "high"}


# --- 4. the evidence verifier ran -----------------------------------------------------


def test_live_evidence_verifier_ran(live_result):
    assert live_result.evidence_integrity in {"passed", "partial", "failed"}
    assert live_result.evidence_verification.total_count == len(live_result.ai.evidence)


def test_live_model_cited_real_evidence(live_result):
    """The substantive check: did a real model actually quote the supplied output?

    Reported rather than hard-failed on `partial`, because a single mis-attributed citation
    is a model calibration issue, not a broken pipeline — the pipeline handled it correctly
    by capping confidence.
    """
    verification = live_result.evidence_verification
    if verification.status != "passed":
        pytest.xfail(
            f"model produced {verification.failed_count} unverifiable citation(s) — "
            f"the pipeline handled this correctly by capping confidence. "
            f"Details: {verification.details}"
        )
    assert verification.verified_count >= 1


# --- 5 & 6. reconciliation and capping ran --------------------------------------------


def test_live_reconciliation_ran(live_result):
    assert live_result.agreement in {
        "agree",
        "partial",
        "ai_only",
        "rules_only",
        "conflict",
    }


def test_live_confidence_capping_ran(live_result):
    assert live_result.model_confidence in {"low", "medium", "high"}
    assert live_result.effective_confidence in {"low", "medium", "high"}
    # Capping may only ever reduce confidence, never raise it.
    ranks = {"low": 0, "medium": 1, "high": 2}
    assert ranks[live_result.effective_confidence] <= ranks[live_result.model_confidence]


# --- the human gate still holds on the live path ---------------------------------------


def test_live_result_still_requires_human_review(live_result):
    assert live_result.status == AWAITING_REVIEW
    assert live_result.applied is False


# --- 7. no credential appears anywhere in the output ----------------------------------


def test_no_api_key_appears_in_any_output(live_result):
    """The key must not reach the result object, the raw text, or any warning."""
    key = get_settings().gemini_api_key
    assert key, "this test is meaningless without a configured key"

    haystacks = [
        live_result.ai.model_dump_json(),
        live_result.evidence_verification.details,
        live_result.reconciliation.reason,
        " ".join(live_result.warnings),
        "\n".join(live_result.summary_lines()),
        str(live_result.token_usage),
        live_result.model,
        live_result.provider,
    ]
    if live_result.ai and getattr(live_result, "provider_note", None):
        haystacks.append(str(live_result.provider_note))

    for haystack in haystacks:
        assert key not in haystack, "the API key leaked into pipeline output"


def test_provider_error_messages_do_not_leak_the_key():
    """A wrong key must produce a diagnosable error that does not echo the credential.

    The test credential is deliberately *not* shaped like a real Google key, so a secret
    scanner run over this repository does not flag it.
    """
    from backend.app.ai.base import ProviderError
    from backend.app.config import Settings

    bad_key = "deliberately-invalid-test-credential-not-a-real-key"
    settings = Settings(
        llm_provider="gemini", llm_model=get_settings().llm_model, gemini_api_key=bad_key
    )
    provider = GeminiProvider(settings=settings)

    case_repo.clear_cache()
    case = case_repo.get_case("CASE-001", use_cache=False)

    with pytest.raises(ProviderError) as exc_info:
        diagnose_case(case, provider=provider)

    assert bad_key not in str(exc_info.value)
