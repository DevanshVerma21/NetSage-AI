"""Anthropic provider — a second live provider behind the same abstraction.

Implemented in Phase 6 only because the Gemini free tier's daily quota was exhausted mid-batch
and the evaluation still had cases to run. Nothing outside this file and one branch in
``factory.py`` changed: the diagnosis service, the prompt, the evidence verifier, the
reconciler and the confidence caps are shared with Gemini, so a result produced here is graded
by exactly the same deterministic machinery.

Structured output is obtained by asking for a bare JSON object and validating it against
``AIDiagnosis`` locally, reusing the same one-shot repair loop as the Gemini path. The
installed SDK has no ``messages.parse``, and local validation is the stricter check anyway
because it enforces ``extra="forbid"`` and the cross-field rules a wire schema cannot express.

Credential handling matches the Gemini provider: the key is read from configuration into the
SDK client and never logged, printed, echoed into an exception message, or placed on a
returned object.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from pydantic import ValidationError

from backend.app.ai.base import DiagnoseRequest, ProviderError, ProviderResult
from backend.app.ai.gemini_provider import _is_transient, _strip_fences
from backend.app.ai.prompt_loader import system_instruction
from backend.app.config import Settings, get_settings
from backend.app.models.diagnosis import AIDiagnosis

MAX_REPAIR_ATTEMPTS = 1
MAX_TRANSIENT_RETRIES = 3
RETRY_BASE_DELAY_SECONDS = 2.0
TEMPERATURE = 0.1
MAX_OUTPUT_TOKENS = 8192

JSON_ONLY_INSTRUCTION = (
    "Respond with a single JSON object matching the required schema and nothing else. "
    "No prose, no markdown fence, no commentary before or after the object."
)


class AnthropicProvider:
    """Live provider backed by the ``anthropic`` SDK."""

    def __init__(
        self, settings: Optional[Settings] = None, model: Optional[str] = None
    ) -> None:
        self._settings = settings or get_settings()
        self.name = "anthropic"
        # ``llm_model`` names the Gemini model, so this provider carries its own setting and
        # never inherits a model name that belongs to another vendor.
        self.model = model or self._settings.anthropic_model
        self._client: Any = None

    # --- availability ------------------------------------------------------------------

    def is_available(self) -> bool:
        """True when a key is configured. Does not make a network call."""
        return bool(self._settings.anthropic_api_key)

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        if not self.is_available():
            raise ProviderError(
                "ANTHROPIC_API_KEY is not configured. Set it in .env, or set "
                "LLM_PROVIDER=mock to run the prototype offline."
            )

        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise ProviderError(
                "anthropic is not installed. Run: pip install -r backend/requirements.txt"
            ) from exc

        self._client = anthropic.Anthropic(api_key=self._settings.anthropic_api_key)
        return self._client

    # --- the call ----------------------------------------------------------------------

    def diagnose(self, request: DiagnoseRequest) -> ProviderResult:
        client = self._get_client()
        system = f"{system_instruction()}\n\n{JSON_ONLY_INSTRUCTION}"
        contents = request.render()

        started = time.perf_counter()
        response = self._generate(client, contents, system)
        raw_text = self._response_text(response)
        diagnosis, repair_attempts = self._parse(client, raw_text, contents, system)
        latency_ms = int((time.perf_counter() - started) * 1000)

        return ProviderResult(
            diagnosis=diagnosis,
            provider=self.name,
            model=self.model,
            latency_ms=latency_ms,
            token_usage=self._token_usage(response),
            raw_text=raw_text,
            repair_attempts=repair_attempts,
        )

    def _generate(self, client: Any, contents: str, system: str) -> Any:
        """Call the API, retrying transient server-side failures with backoff.

        Same policy as the Gemini path: 429/5xx are about capacity rather than about the
        request, so they are retried a bounded number of times; anything else fails at once.
        """
        last_exc: Optional[Exception] = None
        made = 0

        for attempt in range(MAX_TRANSIENT_RETRIES + 1):
            made = attempt + 1
            try:
                return client.messages.create(
                    model=self.model,
                    max_tokens=MAX_OUTPUT_TOKENS,
                    temperature=TEMPERATURE,
                    system=system,
                    messages=[{"role": "user", "content": contents}],
                )
            except Exception as exc:
                last_exc = exc
                if attempt >= MAX_TRANSIENT_RETRIES or not _is_transient(exc):
                    break
                time.sleep(RETRY_BASE_DELAY_SECONDS * (2**attempt))

        # Reports the number of calls actually made, not the maximum: a 403 that failed once
        # must not be described as four attempts. Reports only the exception's type and
        # message, and never touches the settings object, so no credential can reach the error
        # text or the traceback.
        raise ProviderError(
            f"Anthropic request failed for model '{self.model}' after {made} attempt(s): "
            f"{type(last_exc).__name__}: {last_exc}"
        ) from last_exc

    def _parse(
        self, client: Any, raw_text: Optional[str], contents: str, system: str
    ) -> tuple[AIDiagnosis, int]:
        attempts = 0
        text = raw_text
        last_error: Optional[Exception] = None

        while attempts <= MAX_REPAIR_ATTEMPTS:
            if text:
                try:
                    return AIDiagnosis.model_validate_json(_strip_fences(text)), attempts
                except (ValidationError, ValueError) as exc:
                    last_error = exc

            if attempts == MAX_REPAIR_ATTEMPTS:
                break

            attempts += 1
            repair_prompt = (
                f"{contents}\n\n"
                "Your previous response did not satisfy the required schema. "
                f"The validation error was:\n{last_error}\n\n"
                "Return the corrected JSON object only. Do not add commentary."
            )
            text = self._response_text(self._generate(client, repair_prompt, system))

        raise ProviderError(
            f"Anthropic returned output that does not match the AIDiagnosis schema after "
            f"{attempts} repair attempt(s): {last_error}"
        )

    # --- response helpers --------------------------------------------------------------

    @staticmethod
    def _response_text(response: Any) -> Optional[str]:
        for block in getattr(response, "content", None) or []:
            text = getattr(block, "text", None)
            if text:
                return text
        return None

    @staticmethod
    def _token_usage(response: Any) -> Optional[dict[str, int]]:
        """Best-effort token metadata. Optional by design — never required."""
        usage = getattr(response, "usage", None)
        if usage is None:
            return None
        counts = {
            "prompt_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
        }
        cleaned = {k: v for k, v in counts.items() if isinstance(v, int)}
        if len(cleaned) == 2:
            cleaned["total_tokens"] = cleaned["prompt_tokens"] + cleaned["output_tokens"]
        return cleaned or None
