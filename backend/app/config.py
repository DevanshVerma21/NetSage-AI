"""Application settings, sourced from the environment / .env.

API keys are never hard-coded and never logged. ``.env`` is gitignored; ``.env.example``
documents the shape.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository root: backend/app/config.py -> backend/app -> backend -> <root>
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- AI provider -----------------------------------------------------------------
    llm_provider: Literal["gemini", "mock", "anthropic"] = "gemini"

    # gemini-3.6-flash rather than gemini-3.7-flash: 3.7 is the newest stable Flash model,
    # but it returns a persistent 503 ("experiencing high demand") on the free tier, which
    # makes it unusable for a demo. 3.6-flash is the newest Flash model with capacity, and
    # this is a one-line change in .env when 3.7 frees up.
    llm_model: str = "gemini-3.6-flash"

    # The Anthropic model carries its own setting: ``llm_model`` names a Gemini model, and a
    # provider must never inherit a model name belonging to another vendor. Override with
    # ANTHROPIC_MODEL in .env.
    anthropic_model: str = "claude-sonnet-5"

    gemini_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None

    # --- paths -----------------------------------------------------------------------
    data_dir: str = "data"
    prompts_dir: str = "prompts"

    @property
    def data_path(self) -> Path:
        path = Path(self.data_dir)
        return path if path.is_absolute() else PROJECT_ROOT / path

    @property
    def prompts_path(self) -> Path:
        path = Path(self.prompts_dir)
        return path if path.is_absolute() else PROJECT_ROOT / path

    def provider_is_configured(self) -> bool:
        """Whether the selected provider has the credentials it needs.

        ``mock`` needs nothing, which is what makes the prototype runnable with no key.
        """
        if self.llm_provider == "mock":
            return True
        if self.llm_provider == "gemini":
            return bool(self.gemini_api_key)
        if self.llm_provider == "anthropic":
            return bool(self.anthropic_api_key)
        return False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
