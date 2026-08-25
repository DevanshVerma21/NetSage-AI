"""Provider selection.

The single place in the codebase that knows which concrete providers exist. Adding a
provider means adding a module and one branch here; no caller changes.
"""

from __future__ import annotations

from typing import Optional

from backend.app.ai.base import LLMProvider, ProviderError
from backend.app.config import Settings, get_settings

KNOWN_PROVIDERS = ("gemini", "mock", "anthropic")


def build_provider(
    name: Optional[str] = None, settings: Optional[Settings] = None
) -> LLMProvider:
    """Instantiate a provider by name, defaulting to the configured one."""
    settings = settings or get_settings()
    provider_name = (name or settings.llm_provider).strip().lower()

    if provider_name == "mock":
        from backend.app.ai.mock_provider import MockProvider

        return MockProvider()

    if provider_name == "gemini":
        from backend.app.ai.gemini_provider import GeminiProvider

        return GeminiProvider(settings=settings)

    if provider_name == "anthropic":
        from backend.app.ai.anthropic_provider import AnthropicProvider

        return AnthropicProvider(settings=settings)

    raise ProviderError(
        f"unknown LLM_PROVIDER '{provider_name}'. Valid values: {', '.join(KNOWN_PROVIDERS)}"
    )


def build_provider_with_fallback(
    name: Optional[str] = None, settings: Optional[Settings] = None
) -> tuple[LLMProvider, Optional[str]]:
    """Return the requested provider, or fall back to mock when it has no credentials.

    Returns ``(provider, fallback_note)``. The note is non-None whenever a fallback happened,
    so the caller can surface it rather than silently serving mock output as if it were a
    real model answer.
    """
    settings = settings or get_settings()
    requested = (name or settings.llm_provider).strip().lower()

    provider = build_provider(requested, settings)
    if provider.is_available():
        return provider, None

    from backend.app.ai.mock_provider import MockProvider

    note = (
        f"Provider '{requested}' is not configured (no API key present), so the "
        "deterministic MOCK provider was used instead. This output is not a language-model "
        "answer."
    )
    return MockProvider(), note
