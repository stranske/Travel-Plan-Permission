"""SQLite-backed portal state store with WAL and per-record upserts.

This is the default persistence backend when ``TPP_PORTAL_DATABASE_URL`` is
not set. The store uses three tables:

* ``schema_version`` — single-row migration marker.
* ``portal_records`` — per-record rows for mapped namespaces (drafts,
  proposals, manager reviews, exception requests).
* ``portal_singletons`` — single-row payload for lists such as audit events.
  Review indexes are keyed records; initialization migrates legacy index blobs.

``save_snapshot`` merges keyed records by default. With ``replace=True``,
it reconciles each mapped namespace inside a single transaction: rows whose
keys are absent from the authoritative snapshot are deleted before upserts. This keeps SQL-backed restart
state aligned with in-memory LRU eviction for portal drafts, expense drafts,
manager reviews, submissions, plans, and exception requests.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .sql_store import SqlSnapshotStore

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


class SQLitePortalStateStore(SqlSnapshotStore):
    """SQLite-backed portal state store using WAL and a per-store write lock.

    The HTTP service shares one store instance across synchronous routes.  The
    lock serializes ``BEGIN IMMEDIATE``/commit pairs on that one SQLite
    connection; WAL still permits concurrent readers.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path).expanduser().resolve()
        self._conn: sqlite3.Connection | None = None
        self._write_lock = threading.RLock()

    @contextmanager
    def service_operation(self) -> Iterator[None]:
        """Serialize full service operations separately from data commits.

        A SQLite sidecar holds only the coordination transaction. Data saves
        commit on the primary connection before audit outbox delivery.
        """
        with self._write_lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            lock_path = self._path.with_name(self._path.name + ".service-lock.sqlite3")
            lock = sqlite3.connect(lock_path, timeout=30, isolation_level=None)
            try:
                lock.execute("BEGIN IMMEDIATE")
                yield
                lock.execute("COMMIT")
            finally:
                lock.close()

    @property
    def path(self) -> Path:
        return self._path

    def _connection(self) -> sqlite3.Connection:
        with self._write_lock:
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
        with self._write_lock:
            conn = self._connection()
            with _transaction(conn, self._write_lock):
                for stmt in _SCHEMA_STATEMENTS:
                    conn.execute(stmt)
                conn.execute(
                    "INSERT OR IGNORE INTO schema_version (version, applied_at) " "VALUES (?, ?)",
                    (SCHEMA_VERSION, _now_iso()),
                )
                legacy = conn.execute(
                    "SELECT payload_json FROM portal_singletons WHERE namespace = ?",
                    ("review_ids_by_draft_id",),
                ).fetchone()
                if legacy is not None:
                    index = json.loads(legacy[0])
                    if not isinstance(index, dict):
                        raise ValueError("legacy review index is not a mapping")
                    for key, value in index.items():
                        conn.execute(
                            "INSERT OR IGNORE INTO portal_records VALUES (?, ?, ?, ?)",
                            ("review_ids_by_draft_id", str(key), json.dumps(value), _now_iso()),
                        )
                    conn.execute(
                        "DELETE FROM portal_singletons WHERE namespace = ?",
                        ("review_ids_by_draft_id",),
                    )

    def _select_all(self) -> tuple[list[tuple[str, str, object]], list[tuple[str, object]]]:
        with self._write_lock:
            conn = self._connection()
            records = conn.execute(
                "SELECT namespace, record_key, payload_json FROM portal_records"
            ).fetchall()
            singletons = conn.execute(
                "SELECT namespace, payload_json FROM portal_singletons"
            ).fetchall()
            return records, singletons

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._write_lock:
            conn = self._connection()
            with _transaction(conn, self._write_lock) as handle:
                yield handle

    def _delete_absent_records(
        self, handle: sqlite3.Connection, namespace: str, record_keys: list[str]
    ) -> None:
        # Select and delete stale keys with fixed-size bindings. A NOT IN list
        # consumes one SQLite variable per retained key and can exceed the
        # connection's runtime limit even for an otherwise valid snapshot.
        retained = set(record_keys)
        existing = handle.execute(
            "SELECT record_key FROM portal_records WHERE namespace = ?",
            (namespace,),
        ).fetchall()
        handle.executemany(
            "DELETE FROM portal_records WHERE namespace = ? AND record_key = ?",
            ((namespace, key) for (key,) in existing if key not in retained),
        )

    def _upsert_record(
        self,
        handle: sqlite3.Connection,
        namespace: str,
        record_key: str,
        payload: object,
        updated_at: object,
    ) -> None:
        handle.execute(
            "INSERT INTO portal_records "
            "(namespace, record_key, payload_json, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(namespace, record_key) DO UPDATE SET "
            "payload_json=excluded.payload_json, "
            "updated_at=excluded.updated_at",
            (
                namespace,
                record_key,
                json.dumps(payload, sort_keys=True),
                updated_at,
            ),
        )

    def _upsert_singleton(
        self,
        handle: sqlite3.Connection,
        namespace: str,
        payload: object,
        updated_at: object,
    ) -> None:
        handle.execute(
            "INSERT INTO portal_singletons "
            "(namespace, payload_json, updated_at) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(namespace) DO UPDATE SET "
            "payload_json=excluded.payload_json, "
            "updated_at=excluded.updated_at",
            (namespace, json.dumps(payload, sort_keys=True), updated_at),
        )

    def _now(self) -> str:
        return _now_iso()

    def close(self) -> None:
        with self._write_lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def journal_mode(self) -> str:
        """Return the active SQLite journal mode (test/diagnostic helper)."""
        with self._write_lock:

            conn = self._connection()
            row = conn.execute("PRAGMA journal_mode").fetchone()
            return str(row[0]) if row else ""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class _transaction:  # noqa: N801 — context-manager style is the public surface here
    """Best-effort BEGIN IMMEDIATE/COMMIT context manager."""

    def __init__(self, conn: sqlite3.Connection, write_lock: threading.RLock | None = None) -> None:
        self._conn = conn
        self._write_lock = write_lock or threading.RLock()

    def __enter__(self) -> sqlite3.Connection:
        self._write_lock.acquire()
        try:
            self._conn.execute("BEGIN IMMEDIATE")
        except BaseException:
            self._write_lock.release()
            raise
        return self._conn

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        try:
            if exc_type is None:
                self._conn.execute("COMMIT")
            else:
                self._conn.execute("ROLLBACK")
        finally:
            self._write_lock.release()
