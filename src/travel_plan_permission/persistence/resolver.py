"""Backend resolution for the planner HTTP service portal store.

The resolver examines the environment and the configured state path to pick
between SQLite (the default), Postgres (env-gated by
``TPP_PORTAL_DATABASE_URL``), and the legacy JSON backend (selected by a
``.json`` suffix on ``TPP_PORTAL_STATE_PATH``). It also runs the one-shot
legacy importer when a stale ``var/portal-runtime-state.json`` exists next
to a fresh SQLite file.
"""

from __future__ import annotations

import os
from pathlib import Path

from .importer import maybe_import_legacy_state
from .json_store import JsonPortalStateStore
from .sqlite_store import SQLitePortalStateStore
from .store import PortalStateStore

PORTAL_DATABASE_URL_ENV = "TPP_PORTAL_DATABASE_URL"
PORTAL_BACKEND_ENV = "TPP_PORTAL_BACKEND"


def resolve_portal_state_store(state_path: Path | None) -> PortalStateStore | None:
    """Return the configured :class:`PortalStateStore` for the given state path.

    ``state_path is None`` means "no persistence" (in-memory only). In that
    case the resolver returns ``None`` and the caller should not load or save
    snapshots. This matches the original behavior of
    :class:`PlannerProposalStore` when no path was supplied.

    Resolution order:

    1. ``TPP_PORTAL_DATABASE_URL`` set → Postgres.
    2. ``state_path`` ends in ``.json`` (or ``TPP_PORTAL_BACKEND=json``) →
       deprecated JSON store at that path.
    3. Otherwise → SQLite at ``state_path`` (with the suffix normalized to
       ``.sqlite3``). When a sibling JSON file exists and the SQLite store
       is fresh, the importer copies the legacy state forward.
    """

    database_url = os.getenv(PORTAL_DATABASE_URL_ENV)
    if database_url:
        return _build_postgres_store(database_url)

    if state_path is None:
        return None

    explicit_backend = os.getenv(PORTAL_BACKEND_ENV, "").strip().lower()
    if explicit_backend == "json" or _looks_like_json(state_path):
        store: PortalStateStore = JsonPortalStateStore(state_path)
        store.initialize()
        return store

    sqlite_path = _coerce_sqlite_path(state_path)
    sqlite_store = SQLitePortalStateStore(sqlite_path)
    sqlite_store.initialize()

    legacy_candidate = state_path.with_suffix(".json")
    maybe_import_legacy_state(sqlite_store, legacy_candidate)
    return sqlite_store


def _build_postgres_store(database_url: str) -> PortalStateStore:
    # Lazy import so SQLite-only environments don't pay the cost of pulling
    # the typing-only psycopg reference at module import time.
    from .postgres_store import PostgresPortalStateStore

    store = PostgresPortalStateStore(database_url)
    store.initialize()
    return store


def _looks_like_json(path: Path) -> bool:
    return path.suffix.lower() == ".json"


def _coerce_sqlite_path(path: Path) -> Path:
    if path.suffix.lower() == ".sqlite3":
        return path
    return path.with_suffix(".sqlite3")
