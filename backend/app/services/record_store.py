"""JSON-file collections for the Phase 3 records.

One file per collection under ``data/``: ``diagnoses.json``, ``reviews.json``,
``fix_runs.json``. No database — the volumes involved are a few hundred records, the files
stay diffable in git, and every graded deliverable is already a plain file.

Reads tolerate a missing or empty file (returning an empty collection), writes go through
:func:`backend.app.store.write_json`, which is atomic, and a re-entrant lock serialises
read-modify-write sequences so a concurrent append and update cannot lose a record.

``records_dir`` is a function rather than a constant so tests can point the whole store at
a temporary directory without touching the repository's real data files.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Generic, Optional, TypeVar

from pydantic import BaseModel

from backend.app.config import get_settings
from backend.app.store import read_json, write_json

T = TypeVar("T", bound=BaseModel)

_LOCK = threading.RLock()

DIAGNOSES_FILE = "diagnoses.json"
REVIEWS_FILE = "reviews.json"
FIX_RUNS_FILE = "fix_runs.json"


def records_dir() -> Path:
    """Directory holding the record files. Monkeypatched in tests."""
    return get_settings().data_path


class JsonCollection(Generic[T]):
    """A list of Pydantic records persisted as one JSON array."""

    def __init__(
        self,
        filename: str,
        model: type[T],
        id_field: str,
        derived_fields: tuple[str, ...] = (),
    ) -> None:
        self.filename = filename
        self.model = model
        self.id_field = id_field
        # Fields a record computes from its own data. They are served to clients but not
        # written to disk: storing a value that is derived from a neighbouring field is how
        # a file ends up disagreeing with itself after an edit.
        self.derived_fields = derived_fields

    # --- location ----------------------------------------------------------------------

    @property
    def path(self) -> Path:
        return records_dir() / self.filename

    # --- reads -------------------------------------------------------------------------

    def all(self) -> list[T]:
        """Every record, oldest first. Returns ``[]`` when the file does not exist yet."""
        with _LOCK:
            raw = read_json(self.path, default=[])
        if not isinstance(raw, list):
            raise ValueError(f"{self.path} does not contain a JSON list")
        return [self.model.model_validate(entry) for entry in raw]

    def get(self, record_id: str) -> Optional[T]:
        wanted = record_id.strip().lower()
        for record in self.all():
            if str(getattr(record, self.id_field)).lower() == wanted:
                return record
        return None

    def find(self, predicate: Callable[[T], bool]) -> list[T]:
        return [record for record in self.all() if predicate(record)]

    def first(self, predicate: Callable[[T], bool]) -> Optional[T]:
        for record in self.all():
            if predicate(record):
                return record
        return None

    def count(self) -> int:
        return len(self.all())

    # --- writes ------------------------------------------------------------------------

    def append(self, record: T) -> T:
        """Add one record. Raises if its id already exists."""
        with _LOCK:
            existing = self.all()
            record_id = str(getattr(record, self.id_field))
            if any(str(getattr(item, self.id_field)) == record_id for item in existing):
                raise ValueError(f"duplicate {self.id_field}: {record_id}")
            existing.append(record)
            self._write(existing)
        return record

    def update(self, record: T) -> T:
        """Replace the record with the same id. Raises if it is not stored."""
        with _LOCK:
            existing = self.all()
            record_id = str(getattr(record, self.id_field))
            for index, item in enumerate(existing):
                if str(getattr(item, self.id_field)) == record_id:
                    existing[index] = record
                    self._write(existing)
                    return record
        raise KeyError(f"no {self.model.__name__} with {self.id_field}={record_id}")

    def _write(self, records: list[T]) -> None:
        exclude = set(self.derived_fields) or None
        write_json(
            self.path,
            [record.model_dump(mode="json", exclude=exclude) for record in records],
        )
