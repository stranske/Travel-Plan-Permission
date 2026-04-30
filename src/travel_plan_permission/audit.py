"""Durable, append-only audit-event log for authn, authz, and approval transitions.

This module implements the durable side of the audit trail described in
``docs/audit-trail.md`` and tracked in issue #999. The shipped behavior:

* An ``audit_events`` table backed by SQLite (default) or a caller-supplied
  store. Schema columns mirror the issue spec:
  ``id``, ``occurred_at``, ``actor_subject``, ``actor_role``, ``event_type``,
  ``outcome``, ``target_kind``, ``target_id``, ``metadata_json``.
* A module-level "default store" so emit-sites in ``planner_auth``,
  ``security``, and ``http_service`` can call :func:`write_audit_event`
  without threading a store handle through every signature. When no store is
  installed (e.g. unit tests that don't care), :func:`write_audit_event` is a
  silent no-op.
* A small event-type vocabulary as ``EVENT_*`` constants so callers and
  consumers share one source of truth.
* CSV export and retention pruning helpers used by the ``tpp-audit-export``
  CLI entry point and the documented prune task.

The schema is intentionally append-only; the only delete path is the
documented retention prune, which removes rows strictly older than the
configured retention window (default 7 years, override via
``TPP_AUDIT_RETENTION_DAYS``). External SIEM forwarding and immutable
storage primitives (hash chains, write-once filesystems) remain out of
scope for v1, per the issue.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import sys
import threading
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import IO, Protocol, runtime_checkable
from uuid import uuid4

EVENT_AUTH_REQUEST = "auth.request"
EVENT_AUTH_BOOTSTRAP_MINT = "auth.bootstrap_mint"
EVENT_RBAC_ROLE_CHANGE = "rbac.role_change"
EVENT_RBAC_PERMISSION_CHANGE = "rbac.permission_change"
EVENT_PROPOSAL_STATUS_CHANGE = "proposal.status_change"
EVENT_PROPOSAL_CREATED = "proposal.created"

KNOWN_EVENT_TYPES: frozenset[str] = frozenset(
    {
        EVENT_AUTH_REQUEST,
        EVENT_AUTH_BOOTSTRAP_MINT,
        EVENT_RBAC_ROLE_CHANGE,
        EVENT_RBAC_PERMISSION_CHANGE,
        EVENT_PROPOSAL_STATUS_CHANGE,
        EVENT_PROPOSAL_CREATED,
    }
)

OUTCOME_SUCCESS = "success"
OUTCOME_FAILURE = "failure"

RETENTION_ENV_VAR = "TPP_AUDIT_RETENTION_DAYS"
DEFAULT_RETENTION_DAYS = 365 * 7

CSV_FIELDS: tuple[str, ...] = (
    "id",
    "occurred_at",
    "actor_subject",
    "actor_role",
    "event_type",
    "outcome",
    "target_kind",
    "target_id",
    "metadata_json",
)


@dataclass(frozen=True)
class AuditEvent:
    """Single durable audit-event row.

    ``metadata`` is a JSON-serializable mapping; the persistence layer encodes
    it as ``metadata_json``. ``id`` defaults to a fresh UUID4 hex string and
    ``occurred_at`` defaults to ``datetime.now(UTC)`` so call sites can
    construct events with minimal boilerplate.
    """

    event_type: str
    actor_subject: str
    outcome: str
    actor_role: str | None = None
    target_kind: str | None = None
    target_id: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: str = field(default_factory=lambda: uuid4().hex)

    def as_row(self) -> dict[str, object]:
        """Return the event as a flat ``audit_events`` row."""

        return {
            "id": self.id,
            "occurred_at": self.occurred_at.astimezone(UTC).isoformat(),
            "actor_subject": self.actor_subject,
            "actor_role": self.actor_role,
            "event_type": self.event_type,
            "outcome": self.outcome,
            "target_kind": self.target_kind,
            "target_id": self.target_id,
            "metadata_json": json.dumps(self.metadata, sort_keys=True, separators=(",", ":")),
        }


@runtime_checkable
class AuditEventStore(Protocol):
    """Persistence backend for durable audit events."""

    def initialize(self) -> None:
        """Create schema and prepare the backend for use."""

    def write(self, event: AuditEvent) -> None:
        """Append a single event."""

    def query(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        event_type: str | None = None,
    ) -> Iterator[AuditEvent]:
        """Yield events within an optional time window, ordered by ``occurred_at`` asc."""

    def prune(self, older_than: datetime) -> int:
        """Delete events strictly older than ``older_than`` and return rows removed."""

    def close(self) -> None:
        """Release any underlying connections or file handles."""


class NullAuditEventStore:
    """No-op store used when no durable backend is configured."""

    def initialize(self) -> None:
        return None

    def write(self, event: AuditEvent) -> None:  # noqa: ARG002
        return None

    def query(
        self,
        *,
        since: datetime | None = None,  # noqa: ARG002
        until: datetime | None = None,  # noqa: ARG002
        event_type: str | None = None,  # noqa: ARG002
    ) -> Iterator[AuditEvent]:
        if False:  # pragma: no cover - typing trick for empty generator
            yield AuditEvent(event_type="", actor_subject="", outcome="")
        return
        yield

    def prune(self, older_than: datetime) -> int:  # noqa: ARG002
        return 0

    def close(self) -> None:
        return None


_AUDIT_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS audit_events (
        id TEXT PRIMARY KEY,
        occurred_at TEXT NOT NULL,
        actor_subject TEXT NOT NULL,
        actor_role TEXT,
        event_type TEXT NOT NULL,
        outcome TEXT NOT NULL,
        target_kind TEXT,
        target_id TEXT,
        metadata_json TEXT NOT NULL DEFAULT '{}'
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_audit_events_occurred_at
        ON audit_events (occurred_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_audit_events_event_type
        ON audit_events (event_type)
    """,
)


class SQLiteAuditEventStore:
    """SQLite-backed append-only audit-event store."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path).expanduser()
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

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
            self._conn = conn
        return self._conn

    def initialize(self) -> None:
        conn = self._connection()
        with self._lock:
            conn.execute("BEGIN IMMEDIATE")
            try:
                for stmt in _AUDIT_SCHEMA_STATEMENTS:
                    conn.execute(stmt)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def write(self, event: AuditEvent) -> None:
        conn = self._connection()
        row = event.as_row()
        with self._lock:
            conn.execute(
                "INSERT INTO audit_events "
                "(id, occurred_at, actor_subject, actor_role, event_type, "
                " outcome, target_kind, target_id, metadata_json) "
                "VALUES (:id, :occurred_at, :actor_subject, :actor_role, "
                ":event_type, :outcome, :target_kind, :target_id, :metadata_json)",
                row,
            )

    def query(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        event_type: str | None = None,
    ) -> Iterator[AuditEvent]:
        conn = self._connection()
        clauses: list[str] = []
        params: dict[str, object] = {}
        if since is not None:
            clauses.append("occurred_at >= :since")
            params["since"] = since.astimezone(UTC).isoformat()
        if until is not None:
            clauses.append("occurred_at < :until")
            params["until"] = until.astimezone(UTC).isoformat()
        if event_type is not None:
            clauses.append("event_type = :event_type")
            params["event_type"] = event_type
        sql = (
            "SELECT id, occurred_at, actor_subject, actor_role, event_type, "
            "outcome, target_kind, target_id, metadata_json FROM audit_events"
        )
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY occurred_at ASC, id ASC"
        cursor = conn.execute(sql, params)
        try:
            for row in cursor:
                yield _row_to_event(row)
        finally:
            cursor.close()

    def prune(self, older_than: datetime) -> int:
        conn = self._connection()
        cutoff = older_than.astimezone(UTC).isoformat()
        with self._lock:
            cursor = conn.execute(
                "DELETE FROM audit_events WHERE occurred_at < ?",
                (cutoff,),
            )
            return cursor.rowcount or 0

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


def _row_to_event(row: tuple[object, ...]) -> AuditEvent:
    (
        event_id,
        occurred_at,
        actor_subject,
        actor_role,
        event_type,
        outcome,
        target_kind,
        target_id,
        metadata_json,
    ) = row
    metadata: dict[str, object]
    if metadata_json is None or metadata_json == "":
        metadata = {}
    else:
        try:
            decoded = json.loads(str(metadata_json))
        except json.JSONDecodeError:
            metadata = {"_raw": str(metadata_json)}
        else:
            metadata = decoded if isinstance(decoded, dict) else {"_raw": decoded}
    parsed_occurred = datetime.fromisoformat(str(occurred_at))
    if parsed_occurred.tzinfo is None:
        parsed_occurred = parsed_occurred.replace(tzinfo=UTC)
    return AuditEvent(
        id=str(event_id),
        occurred_at=parsed_occurred,
        actor_subject=str(actor_subject),
        actor_role=None if actor_role is None else str(actor_role),
        event_type=str(event_type),
        outcome=str(outcome),
        target_kind=None if target_kind is None else str(target_kind),
        target_id=None if target_id is None else str(target_id),
        metadata=metadata,
    )


_default_store: AuditEventStore = NullAuditEventStore()
_default_store_lock = threading.Lock()


def set_default_store(store: AuditEventStore | None) -> None:
    """Install the default durable audit-event store.

    Pass ``None`` to disable durable persistence (revert to a no-op sink).
    """

    global _default_store
    with _default_store_lock:
        _default_store = store if store is not None else NullAuditEventStore()


def get_default_store() -> AuditEventStore:
    """Return the currently installed default audit-event store."""

    with _default_store_lock:
        return _default_store


def reset_default_store() -> None:
    """Reset the default store to a :class:`NullAuditEventStore` (test helper)."""

    set_default_store(None)


def write_audit_event(
    event_type: str,
    *,
    actor_subject: str,
    outcome: str,
    actor_role: str | None = None,
    target_kind: str | None = None,
    target_id: str | None = None,
    metadata: dict[str, object] | None = None,
    occurred_at: datetime | None = None,
    store: AuditEventStore | None = None,
) -> AuditEvent:
    """Append a durable audit event using the supplied or default store.

    Returns the constructed :class:`AuditEvent` for callers that want to log
    or inspect the result. When the active store is a
    :class:`NullAuditEventStore`, no row is persisted but the constructed
    event is still returned so callers can mirror it into the in-memory
    ``security.AuditLog``.
    """

    occurred = occurred_at or datetime.now(UTC)
    event = AuditEvent(
        event_type=event_type,
        actor_subject=actor_subject,
        outcome=outcome,
        actor_role=actor_role,
        target_kind=target_kind,
        target_id=target_id,
        metadata=dict(metadata or {}),
        occurred_at=occurred,
    )
    target_store = store or get_default_store()
    target_store.write(event)
    return event


def export_to_csv(
    output: IO[str] | Path | str,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    event_type: str | None = None,
    store: AuditEventStore | None = None,
) -> int:
    """Write events within ``[since, until)`` to ``output`` as CSV.

    ``output`` accepts an open text stream, a filesystem path, or ``"-"`` for
    stdout. Returns the number of rows written. Column order matches
    :data:`CSV_FIELDS`.
    """

    target_store = store or get_default_store()
    events = target_store.query(since=since, until=until, event_type=event_type)
    if isinstance(output, (str, Path)):
        if str(output) == "-":
            return _write_csv(sys.stdout, events)
        path = Path(output).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            return _write_csv(handle, events)
    return _write_csv(output, events)


def _write_csv(stream: IO[str], events: Iterable[AuditEvent]) -> int:
    writer = csv.DictWriter(stream, fieldnames=list(CSV_FIELDS))
    writer.writeheader()
    count = 0
    for event in events:
        writer.writerow(event.as_row())
        count += 1
    return count


def export_to_string(
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    event_type: str | None = None,
    store: AuditEventStore | None = None,
) -> str:
    """Convenience helper: export to an in-memory CSV string."""

    buffer = StringIO()
    export_to_csv(
        buffer,
        since=since,
        until=until,
        event_type=event_type,
        store=store,
    )
    return buffer.getvalue()


def configured_retention_days() -> int:
    """Return the configured retention window, defaulting to 7 years."""

    raw = os.getenv(RETENTION_ENV_VAR)
    if not raw:
        return DEFAULT_RETENTION_DAYS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_RETENTION_DAYS
    return max(1, value)


def prune_audit_events(
    *,
    retention_days: int | None = None,
    now: datetime | None = None,
    store: AuditEventStore | None = None,
) -> int:
    """Delete audit events older than the retention window.

    Returns the number of rows pruned. ``retention_days`` defaults to the
    value of ``TPP_AUDIT_RETENTION_DAYS`` (or 7 years when unset). Rows whose
    age is exactly equal to the retention window are kept; only strictly
    older rows are removed.
    """

    target_store = store or get_default_store()
    days = retention_days if retention_days is not None else configured_retention_days()
    if days <= 0:
        raise ValueError("retention_days must be positive")
    reference = (now or datetime.now(UTC)).astimezone(UTC)
    cutoff = reference - timedelta(days=days)
    return target_store.prune(cutoff)


def event_to_dict(event: AuditEvent) -> dict[str, object]:
    """Serialize an event to a plain dict (e.g. for JSON encoders)."""

    payload = asdict(event)
    payload["occurred_at"] = event.occurred_at.astimezone(UTC).isoformat()
    return payload


def parse_iso_timestamp(raw: str) -> datetime:
    """Parse an ISO-8601 timestamp argument, defaulting to UTC if naive."""

    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def open_default_store(path: Path | str) -> SQLiteAuditEventStore:
    """Open a SQLite-backed audit store at ``path`` and install it as default."""

    store = SQLiteAuditEventStore(Path(path))
    store.initialize()
    set_default_store(store)
    return store


_DEFAULT_AUDIT_STATE_PATH = "var/portal-audit-events.sqlite3"
AUDIT_PATH_ENV_VAR = "TPP_AUDIT_STATE_PATH"


def _resolve_default_audit_path() -> Path:
    raw = os.getenv(AUDIT_PATH_ENV_VAR)
    if raw:
        return Path(raw).expanduser()
    return Path.cwd() / _DEFAULT_AUDIT_STATE_PATH


def _build_export_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tpp-audit-export",
        description=(
            "Export durable audit events between two timestamps as CSV. "
            "Used by reviewers and compliance tooling to pull a window "
            "without direct database access."
        ),
    )
    parser.add_argument(
        "--since",
        required=True,
        help="Inclusive lower bound (ISO-8601, e.g. 2026-04-01 or 2026-04-01T00:00:00Z).",
    )
    parser.add_argument(
        "--until",
        required=True,
        help="Exclusive upper bound (ISO-8601).",
    )
    parser.add_argument(
        "--event-type",
        default=None,
        help="Optional event_type filter (e.g. 'auth.request').",
    )
    parser.add_argument(
        "--output",
        default="-",
        help="Output path, or '-' for stdout (default).",
    )
    parser.add_argument(
        "--store-path",
        default=None,
        help=(
            "Path to the SQLite audit-events database. Defaults to "
            "$TPP_AUDIT_STATE_PATH or var/portal-audit-events.sqlite3."
        ),
    )
    return parser


def export_main(argv: list[str] | None = None) -> int:
    """Entry point for the ``tpp-audit-export`` console script."""

    parser = _build_export_parser()
    args = parser.parse_args(argv)

    try:
        since = parse_iso_timestamp(args.since)
        until = parse_iso_timestamp(args.until)
    except ValueError as exc:
        parser.error(f"Invalid timestamp: {exc}")

    if until <= since:
        parser.error("--until must be strictly after --since")

    if args.event_type is not None and args.event_type not in KNOWN_EVENT_TYPES:
        sys.stderr.write(
            f"warning: --event-type '{args.event_type}' is not in the documented "
            f"event-type vocabulary; export will still run.\n"
        )

    store_path = (
        Path(args.store_path).expanduser()
        if args.store_path is not None
        else _resolve_default_audit_path()
    )
    if not store_path.exists():
        sys.stderr.write(
            f"error: audit-events store not found at {store_path}; "
            f"set TPP_AUDIT_STATE_PATH or pass --store-path.\n"
        )
        return 2

    store = SQLiteAuditEventStore(store_path)
    try:
        store.initialize()
    except sqlite3.DatabaseError as exc:
        sys.stderr.write(f"error: schema mismatch on {store_path}: {exc}\n")
        return 3

    try:
        if args.output == "-":
            count = export_to_csv(
                sys.stdout,
                since=since,
                until=until,
                event_type=args.event_type,
                store=store,
            )
        else:
            count = export_to_csv(
                Path(args.output),
                since=since,
                until=until,
                event_type=args.event_type,
                store=store,
            )
    finally:
        store.close()

    sys.stderr.write(f"exported {count} audit events\n")
    return 0


def prune_main(argv: list[str] | None = None) -> int:
    """Entry point for the ``tpp-audit-prune`` retention task."""

    parser = argparse.ArgumentParser(
        prog="tpp-audit-prune",
        description=(
            "Delete durable audit events older than the configured retention "
            "window. See docs/audit-trail.md for the runbook."
        ),
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=None,
        help=(
            "Override retention window. Defaults to TPP_AUDIT_RETENTION_DAYS " "or 2555 (7 years)."
        ),
    )
    parser.add_argument(
        "--store-path",
        default=None,
        help="Path to the SQLite audit-events database.",
    )
    args = parser.parse_args(argv)

    store_path = (
        Path(args.store_path).expanduser()
        if args.store_path is not None
        else _resolve_default_audit_path()
    )
    store = SQLiteAuditEventStore(store_path)
    store.initialize()
    try:
        removed = prune_audit_events(
            retention_days=args.retention_days,
            store=store,
        )
    finally:
        store.close()
    sys.stderr.write(f"pruned {removed} audit events older than retention window\n")
    return 0
