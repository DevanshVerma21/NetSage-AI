"""Google Gemini provider — the default live provider.

Uses the **stable** ``client.models.generate_content`` path with native structured output.
The newer ``client.interactions`` API is deliberately avoided: the installed SDK emits
``UserWarning: Interactions usage is experimental and may change in future versions``, which
is not a foundation for a graded prototype. Migrating later is a change to this one file.

Credential handling: the key is read from configuration into the SDK client and never
logged, printed, echoed into an exception message, or placed on a returned object.
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional

from pydantic import ValidationError

from backend.app.ai.base import DiagnoseRequest, ProviderError, ProviderResult
from backend.app.ai.prompt_loader import system_instruction
from backend.app.ai.schema_utils import gemini_response_schema
from backend.app.config import Settings, get_settings
from backend.app.models.diagnosis import AIDiagnosis

# How many times to hand a validation error back to the model before giving up.
MAX_REPAIR_ATTEMPTS = 1

# Transient server-side conditions worth retrying: the free tier returns 503 under load and
# 429 when a per-minute quota is hit. Neither indicates a fault in the request.
RETRYABLE_STATUS = (429, 500, 502, 503, 504)
MAX_TRANSIENT_RETRIES = 3
RETRY_BASE_DELAY_SECONDS = 2.0

# Low temperature: this is a diagnostic task where consistency matters more than variety.
TEMPERATURE = 0.1


class GeminiProvider:
    """Live provider backed by ``google-genai``."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._settings = settings or get_settings()
        self.name = "gemini"
        self.model = self._settings.llm_model
        self._client: Any = None

    # --- availability ------------------------------------------------------------------

    def is_available(self) -> bool:
        """True when a key is configured. Does not make a network call."""
        return bool(self._settings.gemini_api_key)

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        if not self.is_available():
            raise ProviderError(
                "GEMINI_API_KEY is not configured. Set it in .env, or set "
                "LLM_PROVIDER=mock to run the prototype offline."
            )

        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise ProviderError(
                "google-genai is not installed. Run: pip install -r backend/requirements.txt"
            ) from exc

        # The key is passed straight into the SDK and held only there.
        self._client = genai.Client(api_key=self._settings.gemini_api_key)
        return self._client

    # --- the call ----------------------------------------------------------------------

    def diagnose(self, request: DiagnoseRequest) -> ProviderResult:
        from google.genai import types

        client = self._get_client()
        system = system_instruction()
        contents = request.render()

        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            # A sanitised dict, not the Pydantic class: the stable endpoint's Schema proto
            # rejects the `additionalProperties` that `extra="forbid"` emits, and has no
            # general `$ref`. See ai/schema_utils.py.
            response_schema=gemini_response_schema(AIDiagnosis),
            temperature=TEMPERATURE,
        )

        started = time.perf_counter()
        response = self._generate(client, contents, config)
        latency_ms = int((time.perf_counter() - started) * 1000)

        raw_text = self._response_text(response)
        diagnosis, repair_attempts = self._parse(
            client, response, raw_text, contents, config, system
        )

        # Repairs happen after the first call, so measure the total elapsed time.
        if repair_attempts:
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

    def _generate(self, client: Any, contents: str, config: Any) -> Any:
        """Call the API, retrying transient server-side failures with backoff.

        The free tier returns 503 under load and 429 on a per-minute quota. Both are about
        capacity, not about the request, so failing the whole diagnosis on the first one
        would make the prototype look broken when it is not.
        """
        last_exc: Optional[Exception] = None

        for attempt in range(MAX_TRANSIENT_RETRIES + 1):
            try:
                return client.models.generate_content(
                    model=self.model, contents=contents, config=config
                )
            except Exception as exc:
                last_exc = exc
                if attempt >= MAX_TRANSIENT_RETRIES or not _is_transient(exc):
                    break
                time.sleep(RETRY_BASE_DELAY_SECONDS * (2**attempt))

        # Deliberately reports only the exception's type and message, and never touches the
        # settings object, so no credential can reach the error text or the traceback.
        raise ProviderError(
            f"Gemini request failed for model '{self.model}' after "
            f"{MAX_TRANSIENT_RETRIES + 1} attempt(s): "
            f"{type(last_exc).__name__}: {last_exc}"
        ) from last_exc

    def _parse(
        self,
        client: Any,
        response: Any,
        raw_text: Optional[str],
        contents: str,
        config: Any,
        system: str,
    ) -> tuple[AIDiagnosis, int]:
        """Validate the response, repairing once if the model returned invalid JSON.

        The API is passed a sanitised dict schema rather than the Pydantic class, so
        ``response.parsed`` is a plain dict rather than an ``AIDiagnosis``. Validation
        therefore happens here — which is the stricter path anyway, since it enforces the
        ``extra="forbid"`` and cross-field rules the wire schema cannot express.
        """
        attempts = 0
        text = raw_text
        last_error: Optional[Exception] = None

        while attempts <= MAX_REPAIR_ATTEMPTS:
            parsed = getattr(response, "parsed", None)
            if isinstance(parsed, AIDiagnosis):
                return parsed, attempts
            if isinstance(parsed, dict):
                try:
                    return AIDiagnosis.model_validate(parsed), attempts
                except (ValidationError, ValueError) as exc:
                    last_error = exc

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
            response = self._generate(client, repair_prompt, config)
            text = self._response_text(response)

        raise ProviderError(
            f"Gemini returned output that does not match the AIDiagnosis schema after "
            f"{attempts} repair attempt(s): {last_error}"
        )

    # --- response helpers --------------------------------------------------------------

    @staticmethod
    def _response_text(response: Any) -> Optional[str]:
        text = getattr(response, "text", None)
        if text:
            return text
        # Fall back to walking candidates if .text is unavailable on this SDK version.
        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", None) or []:
                part_text = getattr(part, "text", None)
                if part_text:
                    return part_text
        return None

    @staticmethod
    def _token_usage(response: Any) -> Optional[dict[str, int]]:
        """Best-effort token metadata. Optional by design — never required."""
        meta = getattr(response, "usage_metadata", None)
        if meta is None:
            return None
        usage = {
            "prompt_tokens": getattr(meta, "prompt_token_count", None),
            "output_tokens": getattr(meta, "candidates_token_count", None),
            "thinking_tokens": getattr(meta, "thoughts_token_count", None),
            "total_tokens": getattr(meta, "total_token_count", None),
        }
        cleaned = {k: v for k, v in usage.items() if isinstance(v, int)}
        return cleaned or None


def _is_transient(exc: Exception) -> bool:
    """Whether an exception represents a retryable capacity problem.

    Reads a status code where the SDK exposes one, and falls back to matching the message,
    so this keeps working if the SDK changes its exception hierarchy.
    """
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if isinstance(code, int) and code in RETRYABLE_STATUS:
        return True

    message = str(exc)
    if any(str(status) in message for status in RETRYABLE_STATUS):
        return True

    lowered = message.lower()
    return any(
        marker in lowered
        for marker in ("unavailable", "high demand", "overloaded", "try again later",
                       "resource_exhausted", "deadline")
    )


def _strip_fences(text: str) -> str:
    """Remove a markdown code fence if the model added one despite instructions."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def schema_converts_cleanly() -> tuple[bool, str]:
    """Verify offline that ``AIDiagnosis`` produces a wire schema the API will accept.

    Checks the properties the live endpoint actually enforces, so a schema regression is
    caught by the offline suite rather than by the first live request.

    Note the limit of this check, learned the hard way: the SDK's own local conversion of the
    Pydantic class succeeded while the API rejected the result, because the stable endpoint's
    Schema proto is narrower than the SDK's validation. This function therefore asserts
    against the proto's constraints, not merely that conversion did not raise.
    """
    try:
        schema = gemini_response_schema(AIDiagnosis)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"

    payload = json.dumps(schema)

    for forbidden in ("$ref", "$defs", "additionalProperties", "$schema"):
        if forbidden in payload:
            return False, f"wire schema still contains '{forbidden}', which the API rejects"

    if schema.get("type") != "OBJECT":
        return False, f"top-level type should be OBJECT, got {schema.get('type')!r}"

    properties = schema.get("properties") or {}
    required_fields = {
        "root_cause",
        "confidence",
        "confidence_score",
        "osi_layer",
        "category",
        "evidence",
        "insufficient_evidence",
        "next_command",
        "fix_steps",
    }
    missing = sorted(required_fields - set(properties))
    if missing:
        return False, f"wire schema is missing required fields: {missing}"

    confidence = properties.get("confidence", {})
    if confidence.get("enum") != ["low", "medium", "high"]:
        return False, f"confidence enum was not preserved: {confidence!r}"

    score = properties.get("confidence_score", {})
    if score.get("minimum") != 0.0 or score.get("maximum") != 1.0:
        return False, f"confidence_score bounds were not preserved: {score!r}"

    evidence_items = (properties.get("evidence") or {}).get("items") or {}
    if "source_command" not in (evidence_items.get("properties") or {}):
        return False, "nested evidence schema was not inlined correctly"

    return True, "ok"
