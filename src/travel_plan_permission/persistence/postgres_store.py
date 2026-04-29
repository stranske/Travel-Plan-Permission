"""Postgres-backed portal state store, gated on TPP_PORTAL_DATABASE_URL.

The driver (``psycopg``) is loaded lazily so the import cost only applies
when a Postgres URL is configured. The schema and per-record-upsert
semantics mirror :class:`SQLitePortalStateStore`; the SQL strings differ only
where Postgres syntax requires (e.g. ``ON CONFLICT`` parameter ordering).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from .store import RECORD_NAMESPACES

if TYPE_CHECKING:  # pragma: no cover — typing-only import
    from psycopg import Connection

SCHEMA_VERSION = 1

_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE SCHEMA IF NOT EXISTS tpp
    """,
    """
    CREATE TABLE IF NOT EXISTS tpp.schema_version (
        version INTEGER PRIMARY KEY,
        applied_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tpp.portal_records (
        namespace TEXT NOT NULL,
        record_key TEXT NOT NULL,
        payload_json JSONB NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (namespace, record_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tpp.portal_singletons (
        namespace TEXT PRIMARY KEY,
        payload_json JSONB NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL
    )
    """,
)


class PostgresPortalStateStore:
    """Postgres-backed portal state store using namespaced ``tpp`` schema."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._conn: Connection | None = None

    @property
    def database_url(self) -> str:
        return self._database_url

    def _connection(self) -> Connection:
        if self._conn is None:
            try:
                import psycopg
            except ImportError as exc:
                raise RuntimeError(
                    "TPP_PORTAL_DATABASE_URL is set but the 'psycopg' driver is "
                    "not installed. Install the optional 'postgres' extra: "
                    "pip install travel-plan-permission[postgres]"
                ) from exc
            self._conn = psycopg.connect(self._database_url, autocommit=False)
        return self._conn

    def initialize(self) -> None:
        conn = self._connection()
        with conn.transaction(), conn.cursor() as cur:
            for stmt in _SCHEMA_STATEMENTS:
                cur.execute(stmt)
            cur.execute(
                "INSERT INTO tpp.schema_version (version, applied_at) "
                "VALUES (%s, %s) ON CONFLICT (version) DO NOTHING",
                (SCHEMA_VERSION, _now()),
            )

    def load_snapshot(self) -> dict[str, object] | None:
        conn = self._connection()
        with conn.cursor() as cur:
            cur.execute("SELECT namespace, record_key, payload_json FROM tpp.portal_records")
            records = cur.fetchall()
            cur.execute("SELECT namespace, payload_json FROM tpp.portal_singletons")
            singletons = cur.fetchall()
        conn.commit()
        if not records and not singletons:
            return None

        snapshot: dict[str, Any] = {namespace: {} for namespace in RECORD_NAMESPACES}
        for namespace, record_key, payload in records:
            snapshot.setdefault(namespace, {})[record_key] = _coerce_jsonb(payload)
        for namespace, payload in singletons:
            snapshot[namespace] = _coerce_jsonb(payload)
        return snapshot

    def save_snapshot(self, snapshot: dict[str, object]) -> None:
        conn = self._connection()
        now = _now()
        with conn.transaction(), conn.cursor() as cur:
            for namespace, value in snapshot.items():
                if namespace in RECORD_NAMESPACES and isinstance(value, dict):
                    for record_key, payload in value.items():
                        cur.execute(
                            "INSERT INTO tpp.portal_records "
                            "(namespace, record_key, payload_json, updated_at) "
                            "VALUES (%s, %s, %s::jsonb, %s) "
                            "ON CONFLICT (namespace, record_key) DO UPDATE SET "
                            "payload_json = EXCLUDED.payload_json, "
                            "updated_at = EXCLUDED.updated_at",
                            (
                                namespace,
                                str(record_key),
                                json.dumps(payload, sort_keys=True),
                                now,
                            ),
                        )
                else:
                    cur.execute(
                        "INSERT INTO tpp.portal_singletons "
                        "(namespace, payload_json, updated_at) "
                        "VALUES (%s, %s::jsonb, %s) "
                        "ON CONFLICT (namespace) DO UPDATE SET "
                        "payload_json = EXCLUDED.payload_json, "
                        "updated_at = EXCLUDED.updated_at",
                        (namespace, json.dumps(value, sort_keys=True), now),
                    )

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


def _now() -> datetime:
    return datetime.now(UTC)


def _coerce_jsonb(value: object) -> object:
    """Return ``value`` as a Python object regardless of psycopg's JSONB shape."""

    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, (str, bytes, bytearray)):
        return json.loads(value)
    return value
