"""SQLite-backed portal state store with WAL and per-record upserts.

This is the default persistence backend when ``TPP_PORTAL_DATABASE_URL`` is
not set. The store uses three tables:

* ``schema_version`` — single-row migration marker.
* ``portal_records`` — per-record rows for mapped namespaces (drafts,
  proposals, manager reviews, exception requests).
* ``portal_singletons`` — single-row payload for namespaces that don't fit
  the keyed model (e.g. ``review_ids_by_draft_id``).

``save_snapshot`` upserts mapped records inside a single transaction. It does
not delete records that are absent from the snapshot; the in-memory
``PlannerProposalStore`` may LRU-evict records on its side, and a follow-up
will add an explicit per-record delete API. Until then, two concurrent
processes can write different ids to the same backing store and both records
survive (per-record CAS at the SQL row level).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .store import RECORD_NAMESPACES

SCHEMA_VERSION = 1

_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS portal_records (
        namespace TEXT NOT NULL,
        record_key TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (namespace, record_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS portal_singletons (
        namespace TEXT PRIMARY KEY,
        payload_json TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
)


class SQLitePortalStateStore:
    """SQLite-backed portal state store using WAL journal mode."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path).expanduser()
        self._conn: sqlite3.Connection | None = None

    @property
    def path(self) -> Path:
        return self._path

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(
                self._path,
                isolation_level=None,
                check_same_thread=False,
            )
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._conn = conn
        return self._conn

    def initialize(self) -> None:
        conn = self._connection()
        with _transaction(conn):
            for stmt in _SCHEMA_STATEMENTS:
                conn.execute(stmt)
            conn.execute(
                "INSERT OR IGNORE INTO schema_version (version, applied_at) "
                "VALUES (?, ?)",
                (SCHEMA_VERSION, _now_iso()),
            )

    def load_snapshot(self) -> dict[str, object] | None:
        conn = self._connection()
        records = conn.execute(
            "SELECT namespace, record_key, payload_json FROM portal_records"
        ).fetchall()
        singletons = conn.execute(
            "SELECT namespace, payload_json FROM portal_singletons"
        ).fetchall()
        if not records and not singletons:
            return None

        snapshot: dict[str, Any] = {namespace: {} for namespace in RECORD_NAMESPACES}
        for namespace, record_key, payload_json in records:
            snapshot.setdefault(namespace, {})[record_key] = json.loads(payload_json)
        for namespace, payload_json in singletons:
            snapshot[namespace] = json.loads(payload_json)
        return snapshot

    def save_snapshot(self, snapshot: dict[str, object]) -> None:
        conn = self._connection()
        now = _now_iso()
        with _transaction(conn):
            for namespace, value in snapshot.items():
                if namespace in RECORD_NAMESPACES and isinstance(value, dict):
                    for record_key, payload in value.items():
                        conn.execute(
                            "INSERT INTO portal_records "
                            "(namespace, record_key, payload_json, updated_at) "
                            "VALUES (?, ?, ?, ?) "
                            "ON CONFLICT(namespace, record_key) DO UPDATE SET "
                            "payload_json=excluded.payload_json, "
                            "updated_at=excluded.updated_at",
                            (
                                namespace,
                                str(record_key),
                                json.dumps(payload, sort_keys=True),
                                now,
                            ),
                        )
                else:
                    conn.execute(
                        "INSERT INTO portal_singletons "
                        "(namespace, payload_json, updated_at) "
                        "VALUES (?, ?, ?) "
                        "ON CONFLICT(namespace) DO UPDATE SET "
                        "payload_json=excluded.payload_json, "
                        "updated_at=excluded.updated_at",
                        (namespace, json.dumps(value, sort_keys=True), now),
                    )

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def journal_mode(self) -> str:
        """Return the active SQLite journal mode (test/diagnostic helper)."""

        conn = self._connection()
        row = conn.execute("PRAGMA journal_mode").fetchone()
        return str(row[0]) if row else ""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class _transaction:  # noqa: N801 — context-manager style is the public surface here
    """Best-effort BEGIN IMMEDIATE/COMMIT context manager."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def __enter__(self) -> sqlite3.Connection:
        self._conn.execute("BEGIN IMMEDIATE")
        return self._conn

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if exc_type is None:
            self._conn.execute("COMMIT")
        else:
            self._conn.execute("ROLLBACK")
