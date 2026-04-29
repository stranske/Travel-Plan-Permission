"""Legacy JSON-file backed portal state store.

This backend matches the historical behavior of
:class:`PlannerProposalStore` writing the entire serialized snapshot to a
single JSON file via atomic rename. It is kept behind a deprecation notice so
existing local state at ``var/portal-runtime-state.json`` can still be read
during the importer transition.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any


class JsonPortalStateStore:
    """Persist portal state to a single JSON file (deprecated)."""

    def __init__(self, path: Path, *, warn_on_use: bool = True) -> None:
        self._path = Path(path).expanduser()
        self._warn_on_use = warn_on_use

    @property
    def path(self) -> Path:
        return self._path

    def initialize(self) -> None:
        if self._warn_on_use:
            sqlite_hint = str(self._path.with_suffix(".sqlite3"))
            warnings.warn(
                f"TPP_PORTAL_STATE_PATH is set to a JSON file path ({self._path}); "
                "the JSON backend is deprecated. Repurpose TPP_PORTAL_STATE_PATH to "
                f"a .sqlite3 path (e.g. {sqlite_hint}) to use the default SQLite "
                "backend, or set TPP_PORTAL_DATABASE_URL for Postgres.",
                DeprecationWarning,
                stacklevel=2,
            )

    def load_snapshot(self) -> dict[str, object] | None:
        if not self._path.exists():
            return None
        result: dict[str, Any] = json.loads(self._path.read_text(encoding="utf-8"))
        return result

    def save_snapshot(self, snapshot: dict[str, object]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_suffix(f"{self._path.suffix}.tmp")
        temp_path.write_text(
            json.dumps(snapshot, sort_keys=True),
            encoding="utf-8",
        )
        temp_path.replace(self._path)

    def close(self) -> None:
        return None
