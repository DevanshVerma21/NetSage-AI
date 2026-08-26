"""AI schema and provider-abstraction tests.

Includes an offline check that the Gemini SDK can still convert ``AIDiagnosis`` into its
own schema dialect — so SDK drift is caught by the test suite rather than by the first live
request in front of an audience.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.ai.base import DiagnoseRequest, LLMProvider
from backend.app.ai.factory import KNOWN_PROVIDERS, build_provider, build_provider_with_fallback
from backend.app.config import Settings
from backend.app.models.diagnosis import AIDiagnosis, Evidence, FixStep


def minimal_diagnosis(**overrides) -> dict:
    payload = {
        "root_cause": "Test cause.",
        "confidence": "medium",
        "confidence_score": 0.6,
        "osi_layer": "L2",
        "category": "VLAN",
        "evidence": [
            {
                "source_command": "show vlan brief",
                "excerpt": "30   SERVERS",
                "why_it_matters": "test",
            }
        ],
        "insufficient_evidence": False,
        "next_command": "show vlan brief",
        "notes_for_reviewer": "test",
    }
    payload.update(overrides)
    return payload


# --- schema validation ----------------------------------------------------------------


def test_valid_diagnosis_parses():
    diagnosis = AIDiagnosis.model_validate(minimal_diagnosis())
    assert diagnosis.confidence == "medium"


@pytest.mark.parametrize("bad", ["HIGH", "certain", "very high", "", "unknown"])
def test_invalid_confidence_values_are_rejected(bad):
    with pytest.raises(ValidationError):
        AIDiagnosis.model_validate(minimal_diagnosis(confidence=bad))


@pytest.mark.parametrize("bad", [-0.1, 1.1, 2.0, -1])
def test_confidence_score_must_be_within_zero_to_one(bad):
    with pytest.raises(ValidationError):
        AIDiagnosis.model_validate(minimal_diagnosis(confidence_score=bad))


def test_confidence_score_boundaries_are_accepted():
    AIDiagnosis.model_validate(minimal_diagnosis(confidence="low", confidence_score=0.0))
    AIDiagnosis.model_validate(minimal_diagnosis(confidence="high", confidence_score=1.0))


@pytest.mark.parametrize("bad", ["L0", "L8", "layer2", "", "PHYSICAL"])
def test_invalid_osi_layers_are_rejected(bad):
    with pytest.raises(ValidationError):
        AIDiagnosis.model_validate(minimal_diagnosis(osi_layer=bad))


@pytest.mark.parametrize("bad", ["vlan", "SPANNING_TREE", "", "OTHER"])
def test_invalid_categories_are_rejected(bad):
    with pytest.raises(ValidationError):
        AIDiagnosis.model_validate(minimal_diagnosis(category=bad))


def test_asserting_a_cause_without_evidence_is_rejected():
    """The core structural guarantee: no unevidenced assertions get through the boundary."""
    with pytest.raises(ValidationError, match="at least one item"):
        AIDiagnosis.model_validate(
            minimal_diagnosis(evidence=[], insufficient_evidence=False)
        )


def test_declining_without_evidence_is_allowed():
    diagnosis = AIDiagnosis.model_validate(
        minimal_diagnosis(evidence=[], insufficient_evidence=True)
    )
    assert diagnosis.evidence == []


def test_empty_strings_are_rejected():
    with pytest.raises(ValidationError):
        AIDiagnosis.model_validate(minimal_diagnosis(root_cause=""))
    with pytest.raises(ValidationError):
        AIDiagnosis.model_validate(minimal_diagnosis(next_command=""))


def test_unknown_fields_are_rejected():
    """extra='forbid' catches a model inventing its own fields."""
    with pytest.raises(ValidationError):
        AIDiagnosis.model_validate(minimal_diagnosis(hallucinated_field="surprise"))


def test_fix_step_order_must_be_contiguous_and_one_based():
    steps = [
        {
            "order": 1,
            "device": "SW1",
            "cli_commands": ["vlan 30"],
            "rationale": "test",
            "risk": "low",
        },
        {
            "order": 5,  # gap
            "device": "SW1",
            "cli_commands": ["no shutdown"],
            "rationale": "test",
            "risk": "low",
        },
    ]
    with pytest.raises(ValidationError, match="contiguous"):
        AIDiagnosis.model_validate(minimal_diagnosis(fix_steps=steps))


def test_fix_step_requires_at_least_one_command():
    with pytest.raises(ValidationError):
        FixStep(order=1, device="SW1", cli_commands=[], rationale="test", risk="low")


@pytest.mark.parametrize("bad", ["critical", "none", "LOW", ""])
def test_fix_step_risk_must_be_valid(bad):
    with pytest.raises(ValidationError):
        FixStep(
            order=1,
            device="SW1",
            cli_commands=["vlan 30"],
            rationale="test",
            risk=bad,
        )


def test_evidence_requires_all_three_fields():
    with pytest.raises(ValidationError):
        Evidence(source_command="show vlan brief", excerpt="", why_it_matters="test")


def test_confidence_band_check():
    """A score outside its label's band is reported, not rejected — it is a calibration
    signal, not grounds for discarding an otherwise usable diagnosis."""
    good = AIDiagnosis.model_validate(
        minimal_diagnosis(confidence="medium", confidence_score=0.6)
    )
    bad = AIDiagnosis.model_validate(
        minimal_diagnosis(confidence="low", confidence_score=0.95)
    )

    assert good.confidence_score_matches_band is True
    assert bad.confidence_score_matches_band is False


def test_enum_conversion_helpers_round_trip():
    diagnosis = AIDiagnosis.model_validate(minimal_diagnosis())

    assert diagnosis.as_osi_layer().value == "L2"
    assert diagnosis.as_category().value == "VLAN"
    assert diagnosis.as_confidence().value == "medium"


# --- provider abstraction -------------------------------------------------------------


def test_mock_provider_satisfies_the_protocol():
    from backend.app.ai.mock_provider import MockProvider

    assert isinstance(MockProvider(), LLMProvider)


def test_gemini_provider_satisfies_the_protocol():
    from backend.app.ai.gemini_provider import GeminiProvider

    assert isinstance(GeminiProvider(), LLMProvider)


def test_anthropic_provider_satisfies_the_protocol():
    """The optional provider must conform even though it is not implemented."""
    from backend.app.ai.anthropic_provider import AnthropicProvider

    assert isinstance(AnthropicProvider(), LLMProvider)


def test_factory_builds_each_known_provider():
    for name in KNOWN_PROVIDERS:
        provider = build_provider(name)
        assert provider.name == name


def test_factory_rejects_an_unknown_provider():
    from backend.app.ai.base import ProviderError

    with pytest.raises(ProviderError, match="unknown LLM_PROVIDER"):
        build_provider("definitely-not-a-provider")


def test_factory_falls_back_to_mock_without_credentials():
    """Without a key the system stays usable, but says so rather than passing mock output
    off as a model answer."""
    settings = Settings(llm_provider="gemini", llm_model="gemini-3.6-flash", gemini_api_key=None)

    provider, note = build_provider_with_fallback(settings=settings)

    assert provider.name == "mock"
    assert note is not None and "not configured" in note


def test_factory_does_not_fall_back_when_a_key_is_present():
    settings = Settings(
        llm_provider="gemini", llm_model="gemini-3.6-flash", gemini_api_key="test-key-value"
    )

    provider, note = build_provider_with_fallback(settings=settings)

    assert provider.name == "gemini"
    assert note is None


def test_model_id_comes_from_configuration_not_a_hard_coded_literal():
    settings = Settings(
        llm_provider="gemini", llm_model="gemini-custom-model", gemini_api_key="k"
    )
    provider = build_provider("gemini", settings=settings)

    assert provider.model == "gemini-custom-model"


def test_unconfigured_gemini_provider_reports_unavailable():
    settings = Settings(llm_provider="gemini", gemini_api_key=None)
    provider = build_provider("gemini", settings=settings)

    assert provider.is_available() is False


def test_anthropic_provider_is_available_only_with_a_key():
    """Implemented in Phase 6 when the Gemini daily quota ran out. Availability tracks the
    credential and makes no network call, exactly as the Gemini provider does."""
    with_key = build_provider(
        "anthropic", settings=Settings(llm_provider="anthropic", anthropic_api_key="some-key")
    )
    assert with_key.is_available() is True

    without_key = build_provider(
        "anthropic", settings=Settings(llm_provider="anthropic", anthropic_api_key=None)
    )
    assert without_key.is_available() is False


def test_anthropic_provider_carries_its_own_model_setting():
    """``llm_model`` names a Gemini model; inheriting it here would report a Gemini model
    name on an Anthropic result and corrupt the evaluation record."""
    settings = Settings(
        llm_provider="anthropic",
        llm_model="gemini-3.6-flash",
        anthropic_model="claude-sonnet-5",
        anthropic_api_key="some-key",
    )
    provider = build_provider("anthropic", settings=settings)

    assert provider.model == "claude-sonnet-5"
    assert provider.name == "anthropic"


def test_anthropic_provider_errors_never_carry_the_credential():
    """The failure path reports the exception type and message only."""
    from backend.app.ai.anthropic_provider import AnthropicProvider
    from backend.app.ai.base import ProviderError

    secret = "sk-ant-do-not-leak-this"
    provider = AnthropicProvider(
        settings=Settings(llm_provider="anthropic", anthropic_api_key=secret)
    )

    class Boom:
        class messages:
            @staticmethod
            def create(**_kwargs):
                raise RuntimeError("403 forbidden")

    with pytest.raises(ProviderError) as excinfo:
        provider._generate(Boom, "contents", "system")

    assert secret not in str(excinfo.value)
    assert "1 attempt(s)" in str(excinfo.value), "a 403 is not retried four times"


def test_no_module_outside_the_ai_layer_imports_the_gemini_sdk():
    """The abstraction is only real if nothing else reaches past it."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "backend"
    offenders = []
    for path in root.rglob("*.py"):
        if path.name in {"gemini_provider.py"}:
            continue
        text = path.read_text(encoding="utf-8")
        if "from google import genai" in text or "import google.genai" in text:
            offenders.append(str(path))

    assert not offenders, f"the Gemini SDK is imported outside the provider: {offenders}"


# --- SDK schema conversion (offline) --------------------------------------------------


def test_gemini_sdk_can_convert_the_diagnosis_schema():
    """Catches SDK drift offline.

    Gemini's schema surface is a documented *subset* of JSON Schema, and Pydantic emits
    ``$defs``/``$ref`` for nested models. This asserts the SDK still inlines them, so a
    conversion regression surfaces here rather than on the first live call.
    """
    from backend.app.ai.gemini_provider import schema_converts_cleanly

    ok, detail = schema_converts_cleanly()
    assert ok, f"AIDiagnosis no longer converts for Gemini: {detail}"

