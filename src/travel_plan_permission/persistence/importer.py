"""One-shot importer that migrates legacy JSON state into the SQL backends."""

from __future__ import annotations

import json
from pathlib import Path

from .store import PortalStateStore


def maybe_import_legacy_state(store: PortalStateStore, legacy_json_path: Path) -> bool:
    """Import a legacy JSON state file into ``store`` if no SQL state exists.

    Returns ``True`` when an import ran and ``False`` otherwise. The legacy
    file is left in place so an out-of-band rollback retains the source data;
    callers may rename it after a successful import.

    The importer is a no-op when the legacy file is missing or unreadable, or
    when the SQL store already contains state. Both conditions are normal at
    runtime: the importer fires once per fresh database.
    """

    legacy_json_path = Path(legacy_json_path).expanduser()
    if not legacy_json_path.exists():
        return False

    existing = store.load_snapshot()
    if existing:
        return False

    try:
        payload = json.loads(legacy_json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    if not isinstance(payload, dict) or not payload:
        return False

    store.save_snapshot(payload)
    return True
