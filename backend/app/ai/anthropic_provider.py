"""Optional Anthropic provider — declared but not wired by default.

Present to demonstrate that the provider abstraction is real: adding a second live provider
requires this file and one branch in ``factory.py``, with no change to the diagnosis service,
the verifier, the reconciler, or any caller.

Deliberately not implemented in Phase 2. The reviewer-approved provider priority is
gemini (default live) -> mock (offline) -> anthropic (optional future), and implementing an
unused second live path would add an untested dependency for no current benefit.
"""

from __future__ import annotations

from typing import Optional

from backend.app.ai.base import DiagnoseRequest, ProviderError, ProviderResult
from backend.app.config import Settings, get_settings


class AnthropicProvider:
    """Placeholder that satisfies the ``LLMProvider`` protocol and fails honestly.

    To implement: ``pip install anthropic``, then call
    ``client.messages.parse(model=..., output_format=AIDiagnosis, ...)`` and return
    ``response.parsed_output`` wrapped in a ``ProviderResult``. The prompt text comes from
    ``prompt_loader.system_instruction()``, unchanged — which is the point of the
    abstraction.
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._settings = settings or get_settings()
        self.name = "anthropic"
        self.model = self._settings.llm_model

    def is_available(self) -> bool:
        """False regardless of credentials: the call path is not implemented.

        Reporting availability on the strength of a key alone would let the factory route
        real traffic into a stub.
        """
        return False

    def diagnose(self, request: DiagnoseRequest) -> ProviderResult:
        raise ProviderError(
            "The Anthropic provider is declared but not implemented in this prototype. "
            "Set LLM_PROVIDER=gemini for the default live provider, or LLM_PROVIDER=mock to "
            "run offline."
        )
