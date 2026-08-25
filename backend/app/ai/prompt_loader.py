"""Prompt library loader and version registry.

Every diagnosis records the name, version and SHA-256 of the prompt that produced it, so a
stored result can always be traced back to the exact instruction text that generated it.
That is what makes a recorded AI answer reproducible — and what makes the responsible-AI
log meaningful, since a correction is only interpretable against a known prompt version.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from backend.app.config import get_settings

REGISTRY_FILENAME = "registry.json"

# Prompts the registry is required to track.
TRACKED_PROMPTS = ("diagnose_prompt", "system_guardrails", "fix_plan_prompt")


@dataclass(frozen=True)
class Prompt:
    """A loaded prompt plus the identity stamped onto every diagnosis that uses it."""

    name: str
    version: str
    sha256: str
    text: str
    path: Path


class PromptError(RuntimeError):
    """Raised when a prompt file or its registry entry is missing or inconsistent."""


def prompts_dir() -> Path:
    return get_settings().prompts_path


def sha256_of_text(text: str) -> str:
    """Hash of prompt text with line endings normalised.

    Normalising CRLF to LF means a Windows checkout and a Linux checkout of the same commit
    produce the same hash, so a recorded prompt hash is portable rather than an artefact of
    whoever ran it.
    """
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def sha256_of_file(path: Path) -> str:
    return sha256_of_text(path.read_text(encoding="utf-8"))


def prompt_path(name: str) -> Path:
    return prompts_dir() / f"{name}.md"


def load_registry(directory: Path | None = None) -> dict:
    path = (directory or prompts_dir()) / REGISTRY_FILENAME
    if not path.exists():
        raise PromptError(
            f"prompt registry not found at {path} — "
            "run: python -m backend.scripts.update_prompt_registry"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def build_registry_payload(directory: Path | None = None) -> dict:
    """Compute the registry content from the prompt files on disk.

    Kept separate from writing so the test can compare the committed registry against a
    freshly computed one without touching the filesystem.
    """
    base = directory or prompts_dir()
    entries = {}
    for name in TRACKED_PROMPTS:
        path = base / f"{name}.md"
        if not path.exists():
            raise PromptError(f"tracked prompt file is missing: {path}")
        text = path.read_text(encoding="utf-8")
        entries[name] = {
            "file": f"{name}.md",
            "version": _extract_version(text, name),
            "sha256": sha256_of_text(text),
        }
    return {
        "registry_version": 1,
        "hash_algorithm": "sha256",
        "hash_note": "computed over the file text with CRLF normalised to LF",
        "prompts": entries,
    }


def _extract_version(text: str, name: str) -> str:
    """Read the ``**Version:** x.y.z`` line out of a prompt's header."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("**Version:**"):
            return stripped.removeprefix("**Version:**").strip()
    raise PromptError(
        f"prompt '{name}' has no '**Version:**' line in its header; "
        "every prompt must declare a version so diagnoses are reproducible"
    )


@lru_cache(maxsize=8)
def load_prompt(name: str) -> Prompt:
    """Load one prompt and verify it matches its registry entry.

    A prompt edited without regenerating the registry raises here rather than silently
    stamping diagnoses with a stale hash.
    """
    path = prompt_path(name)
    if not path.exists():
        raise PromptError(f"prompt not found: {path}")

    text = path.read_text(encoding="utf-8")
    digest = sha256_of_text(text)

    registry = load_registry()
    entry = registry.get("prompts", {}).get(name)
    if entry is None:
        raise PromptError(f"prompt '{name}' is not listed in {REGISTRY_FILENAME}")

    if entry["sha256"] != digest:
        raise PromptError(
            f"prompt '{name}' has changed but {REGISTRY_FILENAME} was not updated "
            f"(registry={entry['sha256'][:12]}..., file={digest[:12]}...) — "
            "run: python -m backend.scripts.update_prompt_registry"
        )

    return Prompt(
        name=name,
        version=entry["version"],
        sha256=digest,
        text=text,
        path=path,
    )


def clear_cache() -> None:
    load_prompt.cache_clear()


def system_instruction() -> str:
    """The full system instruction: shared guardrails followed by the diagnosis prompt."""
    guardrails = load_prompt("system_guardrails")
    diagnose = load_prompt("diagnose_prompt")
    return f"{guardrails.text}\n\n---\n\n{diagnose.text}"
