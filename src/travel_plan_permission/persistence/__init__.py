"""Portal state persistence backends for the planner HTTP service.

The portal HTTP service used to persist all state to a single JSON file at
``var/portal-runtime-state.json``. That backend remains available behind a
deprecation shim, but the default path is now SQLite (with WAL enabled), and a
Postgres backend can be selected via ``TPP_PORTAL_DATABASE_URL``. Each backend
implements :class:`PortalStateStore`, which the
:class:`travel_plan_permission.http_service.PlannerProposalStore` uses to
load/save its serialized snapshot.
"""

from __future__ import annotations

from .importer import maybe_import_legacy_state
from .json_store import JsonPortalStateStore
from .resolver import resolve_portal_state_store
from .sqlite_store import SQLitePortalStateStore
from .store import PortalStateStore

__all__ = [
    "JsonPortalStateStore",
    "PortalStateStore",
    "SQLitePortalStateStore",
    "maybe_import_legacy_state",
    "resolve_portal_state_store",
]
