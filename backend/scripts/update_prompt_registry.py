"""Regenerate prompts/registry.json from the prompt files on disk.

    python -m backend.scripts.update_prompt_registry

Run this after editing any prompt. ``prompt_loader.load_prompt`` refuses to load a prompt
whose hash disagrees with the registry, so a forgotten regeneration fails loudly instead of
stamping diagnoses with a stale prompt identity.
"""

from __future__ import annotations

import json

from backend.app.ai.prompt_loader import (
    REGISTRY_FILENAME,
    build_registry_payload,
    load_registry,
    prompts_dir,
)


def render_registry(payload: dict) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    target = prompts_dir() / REGISTRY_FILENAME
    payload = build_registry_payload()

    previous = None
    if target.exists():
        try:
            previous = load_registry()
        except Exception:  # a malformed existing registry is simply replaced
            previous = None

    target.write_text(render_registry(payload), encoding="utf-8")

    print(f"wrote {target}")
    for name, entry in payload["prompts"].items():
        old = (previous or {}).get("prompts", {}).get(name, {}).get("sha256")
        status = "unchanged" if old == entry["sha256"] else ("updated" if old else "new")
        print(f"  {name:20} v{entry['version']:8} {entry['sha256'][:16]}...  [{status}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
