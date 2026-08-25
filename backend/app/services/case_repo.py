"""Case repository — loads and validates the case dataset.

``data/cases.json`` is the single source of truth. ``data/cases.csv`` (the graded
deliverable) is generated from it, and a test fails if the two ever drift apart.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from backend.app.config import get_settings
from backend.app.models.case import Case, CaseSummary
from backend.app.store import read_json


def cases_file() -> Path:
    return get_settings().data_path / "cases.json"


def load_cases(path: Optional[Path] = None) -> list[Case]:
    """Load and validate every case. Raises on a malformed dataset — a broken dataset
    should fail loudly at startup, not silently produce an empty case library."""
    raw = read_json(path or cases_file(), default=[])
    return [Case.model_validate(entry) for entry in raw]


@lru_cache(maxsize=1)
def _cached_cases() -> tuple[Case, ...]:
    return tuple(load_cases())


def all_cases(use_cache: bool = True) -> list[Case]:
    return list(_cached_cases()) if use_cache else load_cases()


def clear_cache() -> None:
    """Drop the cached dataset. Used by tests and after a dataset edit."""
    _cached_cases.cache_clear()


def get_case(case_id: str, use_cache: bool = True) -> Optional[Case]:
    wanted = case_id.strip().lower()
    for case in all_cases(use_cache=use_cache):
        if case.case_id.lower() == wanted:
            return case
    return None


def summaries(use_cache: bool = True) -> list[CaseSummary]:
    return [CaseSummary.from_case(case) for case in all_cases(use_cache=use_cache)]


def coverage_by_concept(use_cache: bool = True) -> dict[str, int]:
    """Case count per concept tag. Proves the document's category-coverage requirement."""
    counts: dict[str, int] = {}
    for case in all_cases(use_cache=use_cache):
        counts[case.concept_tag.value] = counts.get(case.concept_tag.value, 0) + 1
    return dict(sorted(counts.items()))
