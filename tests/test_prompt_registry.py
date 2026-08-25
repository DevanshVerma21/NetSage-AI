"""Prompt registry and prompt-library tests.

The registry is what makes a stored diagnosis reproducible: it pins the exact instruction
text that produced the answer. These tests also assert the content requirements the company
document places on the prompt library.
"""

from __future__ import annotations

import json

import pytest

from backend.app.ai import prompt_loader
from backend.app.ai.prompt_loader import (
    TRACKED_PROMPTS,
    PromptError,
    build_registry_payload,
    load_prompt,
    load_registry,
    prompt_path,
    prompts_dir,
    sha256_of_text,
    system_instruction,
)


@pytest.fixture(autouse=True)
def _clear_prompt_cache():
    prompt_loader.clear_cache()
    yield
    prompt_loader.clear_cache()


# --- files exist ----------------------------------------------------------------------


def test_the_required_prompt_files_exist():
    """The company document names diagnose_prompt.md specifically."""
    assert prompt_path("diagnose_prompt").exists()
    assert prompt_path("system_guardrails").exists()
    assert prompt_path("fix_plan_prompt").exists()
    assert (prompts_dir() / "registry.json").exists()


# --- N. hashes are reproducible -------------------------------------------------------


def test_hashing_is_reproducible():
    text = "line one\nline two\n"
    assert sha256_of_text(text) == sha256_of_text(text)
    assert len(sha256_of_text(text)) == 64


def test_hashing_normalises_line_endings():
    """A Windows checkout and a Linux checkout of the same commit must hash identically."""
    assert sha256_of_text("a\r\nb\r\n") == sha256_of_text("a\nb\n")
    assert sha256_of_text("a\rb") == sha256_of_text("a\nb")


def test_hashing_still_detects_real_changes():
    assert sha256_of_text("original text") != sha256_of_text("original text.")


def test_committed_registry_matches_the_prompt_files():
    """Fails if a prompt was edited without regenerating the registry."""
    committed = load_registry()
    computed = build_registry_payload()

    assert committed["prompts"] == computed["prompts"], (
        "prompts/registry.json is out of date — run: "
        "python -m backend.scripts.update_prompt_registry"
    )


def test_registry_tracks_every_required_prompt():
    registry = load_registry()
    for name in TRACKED_PROMPTS:
        assert name in registry["prompts"], f"{name} is missing from the registry"
        entry = registry["prompts"][name]
        assert entry["version"]
        assert len(entry["sha256"]) == 64


def test_registry_is_valid_json():
    text = (prompts_dir() / "registry.json").read_text(encoding="utf-8")
    payload = json.loads(text)
    assert payload["hash_algorithm"] == "sha256"


# --- loading --------------------------------------------------------------------------


def test_load_prompt_returns_version_and_hash():
    prompt = load_prompt("diagnose_prompt")

    assert prompt.name == "diagnose_prompt"
    assert prompt.version == "1.0.0"
    assert len(prompt.sha256) == 64
    assert prompt.text.strip()


def test_load_prompt_rejects_an_unknown_prompt():
    with pytest.raises(PromptError, match="prompt not found"):
        load_prompt("no_such_prompt")


def test_load_prompt_detects_a_stale_registry(tmp_path, monkeypatch):
    """Editing a prompt without regenerating the registry must fail loudly, rather than
    stamping diagnoses with a hash that does not describe the text actually used."""
    prompt_file = tmp_path / "diagnose_prompt.md"
    prompt_file.write_text("**Version:** 9.9.9\n\noriginal body\n", encoding="utf-8")

    registry = {
        "registry_version": 1,
        "hash_algorithm": "sha256",
        "prompts": {
            "diagnose_prompt": {
                "file": "diagnose_prompt.md",
                "version": "9.9.9",
                "sha256": "0" * 64,  # deliberately wrong
            }
        },
    }
    (tmp_path / "registry.json").write_text(json.dumps(registry), encoding="utf-8")

    monkeypatch.setattr(prompt_loader, "prompts_dir", lambda: tmp_path)
    prompt_loader.clear_cache()

    with pytest.raises(PromptError, match="was not updated"):
        load_prompt("diagnose_prompt")


def test_prompt_without_a_version_line_is_rejected(tmp_path, monkeypatch):
    for name in TRACKED_PROMPTS:
        (tmp_path / f"{name}.md").write_text("no version header here\n", encoding="utf-8")

    monkeypatch.setattr(prompt_loader, "prompts_dir", lambda: tmp_path)

    with pytest.raises(PromptError, match="no '\\*\\*Version:\\*\\*' line"):
        build_registry_payload()


# --- content requirements from the company document -----------------------------------


def test_diagnose_prompt_requires_the_documented_json_fields():
    text = load_prompt("diagnose_prompt").text
    for field in ("root_cause", "confidence", "evidence", "next_command", "fix_steps"):
        assert field in text, f"the prompt does not mention required field '{field}'"


def test_diagnose_prompt_mentions_the_optional_fields():
    text = load_prompt("diagnose_prompt").text
    for field in (
        "confidence_score",
        "osi_layer",
        "category",
        "insufficient_evidence",
        "alternative_hypotheses",
        "verification_steps",
        "notes_for_reviewer",
    ):
        assert field in text


def test_diagnose_prompt_contains_exactly_three_worked_examples():
    text = load_prompt("diagnose_prompt").text
    headings = [line for line in text.splitlines() if line.startswith("## WORKED EXAMPLE")]

    assert len(headings) == 3, f"expected 3 worked examples, found {len(headings)}"


def test_the_three_examples_cover_the_required_scenarios():
    text = load_prompt("diagnose_prompt").text.lower()

    assert "inter-vlan" in text and "acl" in text          # example 1
    assert "default-router" in text                         # example 2
    assert "insufficient evidence" in text                  # example 3


def test_example_one_holds_confidence_at_medium():
    """The company document's own example says confidence stays medium until route/ACL
    evidence is available."""
    text = load_prompt("diagnose_prompt").text

    assert "show ip route" in text
    assert "show access-lists" in text
    assert "show interfaces trunk" in text
    assert '"confidence": "medium"' in text


def test_example_three_declines_to_guess():
    text = load_prompt("diagnose_prompt").text
    assert '"insufficient_evidence": true' in text
    assert '"fix_steps": []' in text


def test_prompt_enforces_every_required_constraint():
    """The thirteen constraints the phase brief requires the prompt to state."""
    text = load_prompt("diagnose_prompt").text.lower()

    required_ideas = [
        "use only the supplied evidence",
        "never invent show-command output",
        "never invent topology information",
        "must identify its source command",
        "copied from the supplied show output",
        "insufficient",
        "next_command",
        "never claim a fix has been applied",
        "never bypass",
        "human review is always required",
        "high confidence requires corroborating evidence",
        "distinguish observed facts from inference",
        "recommendations, not execution",
    ]
    for idea in required_ideas:
        assert idea in text, f"the prompt does not state: {idea!r}"


def test_guardrails_forbid_execution_and_verification_claims():
    text = load_prompt("system_guardrails").text.lower()

    assert "no execution claims" in text
    assert "no verification claims" in text
    assert "human review is mandatory" in text


def test_fix_plan_prompt_requires_verification_steps():
    text = load_prompt("fix_plan_prompt").text.lower()

    assert "verification_steps" in text
    assert "every fix ends in verification" in text


def test_system_instruction_combines_guardrails_and_diagnosis_prompt():
    combined = system_instruction()

    assert "SYSTEM GUARDRAILS" in combined
    assert "WORKED EXAMPLE 1" in combined
    # Guardrails must come first so they frame everything that follows.
    assert combined.index("SYSTEM GUARDRAILS") < combined.index("WORKED EXAMPLE 1")


def test_prompts_contain_no_secret_shaped_literals():
    """A prompt is committed text; an example key in one would be a leak."""
    import re

    pattern = re.compile(r"AIza[0-9A-Za-z_\-]{20,}|sk-[0-9A-Za-z]{20,}|sk-ant-")
    for name in TRACKED_PROMPTS:
        text = prompt_path(name).read_text(encoding="utf-8")
        assert not pattern.search(text), f"{name} contains a secret-shaped literal"
