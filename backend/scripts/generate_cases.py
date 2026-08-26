"""Generate data/cases.json — the 40-case Phase 5 dataset.

CASE-001 is preserved verbatim from the existing file; CASE-002..040 are produced
by the explicit case definitions in backend/scripts/case_defs/. This script is a
data-generation tool only: it is never imported by the application.

Usage:
    python -m backend.scripts.generate_cases
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

from backend.app.models.case import Case

CASES_JSON = Path("data/cases.json")

CATEGORY_MODULES = [
    "vlan",
    "gateway",
    "dhcp",
    "dns",
    "routing",
    "acl",
    "nat",
    "wireless",
    "interface",
]


def _generated() -> list[dict]:
    out: list[dict] = []
    for name in CATEGORY_MODULES:
        module = importlib.import_module(f"backend.scripts.case_defs.{name}_cases")
        for builder in module.CASES:
            case = Case.model_validate(builder())
            out.append(case.model_dump(mode="json"))
    return out


def _reorder(case: dict, key_order: list[str]) -> dict:
    ordered = {k: case[k] for k in key_order if k in case}
    ordered.update({k: v for k, v in case.items() if k not in ordered})
    return ordered


def main() -> None:
    existing = json.loads(CASES_JSON.read_text(encoding="utf-8"))
    case_001 = next(c for c in existing if c["case_id"] == "CASE-001")
    key_order = list(case_001.keys())

    cases = [case_001] + [_reorder(c, key_order) for c in _generated()]

    ids = [c["case_id"] for c in cases]
    if len(set(ids)) != len(ids):
        raise SystemExit("duplicate case ids generated")
    if len(cases) != 40:
        raise SystemExit(f"expected 40 cases, produced {len(cases)}")

    CASES_JSON.write_text(
        json.dumps(cases, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(cases)} cases to {CASES_JSON}")


if __name__ == "__main__":
    main()
