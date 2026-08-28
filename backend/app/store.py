"""File-backed JSON storage.

The prototype deliberately uses no database: 40 cases and a few hundred records fit
comfortably in JSON, the data stays diffable in git, and the graded deliverables are
plain files. Writes are atomic (temp file + ``os.replace``) and guarded by a lock so a
crash mid-write cannot truncate a data file.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()


def read_json(path: Path, default: Any = None) -> Any:
    """Read a JSON file, returning ``default`` when it does not exist or is empty."""
    if not path.exists():
        return default if default is not None else []
    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        return default if default is not None else []
    return json.loads(text)


def write_json(path: Path, payload: Any) -> None:
    """Atomically write JSON, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
            os.replace(tmp_name, path)
        except BaseException:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
            raise


def append_json(path: Path, record: dict) -> dict:
    """Append one record to a JSON list file and return it."""
    with _LOCK:
        existing = read_json(path, default=[])
        if not isinstance(existing, list):
            raise ValueError(f"{path} does not contain a JSON list")
        existing.append(record)
    write_json(path, existing)
    return record
