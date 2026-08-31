"""The audit log's schema guard, its export, and what it does with unreadable evidence.

An audit log is the record consulted when someone asks what happened. Every failure here is
therefore a compliance failure rather than a bug: a schema mismatch writes events into the wrong
columns, an unreadable metadata blob silently drops the detail somebody is looking for, and an
export that loses a timezone makes two events impossible to order.

None of these paths raise in normal use, which is why they were unexercised.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from io import StringIO

import pytest

from travel_plan_permission import audit


@pytest.fixture()
def store(tmp_path):
    s = audit.SQLiteAuditEventStore(tmp_path / "audit.db")
    s.initialize()
    return s


# ---------------------------------------------------------------------------------------------
# The schema guard.
# ---------------------------------------------------------------------------------------------


def test_a_correct_schema_passes(store, tmp_path):
    """The control: a guard that rejected everything would satisfy the mismatch test below."""
    with sqlite3.connect(tmp_path / "audit.db") as conn:
        audit._validate_audit_events_schema(conn)


def test_a_mismatched_schema_is_refused_and_names_both_sides(tmp_path):
    """Writing into a table whose columns have moved silently misfiles every event.

    The error carries the expected AND actual column lists, because an operator staring at a
    migration needs to see which column moved, not just that something did.
    """
    path = tmp_path / "wrong.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE audit_events (id TEXT, occurred_at TEXT)")
        with pytest.raises(sqlite3.DatabaseError) as excinfo:
            audit._validate_audit_events_schema(conn)
    message = str(excinfo.value)
    assert "schema mismatch" in message
    assert "metadata_json" in message, "the expected columns must be listed"
    assert "occurred_at" in message


def test_a_missing_table_is_reported_as_missing(tmp_path):
    """An absent table and a reordered one are different problems with different fixes."""
    path = tmp_path / "empty.db"
    with sqlite3.connect(path) as conn, pytest.raises(sqlite3.DatabaseError) as excinfo:
        audit._validate_audit_events_schema(conn)
    assert "<missing>" in str(excinfo.value)


# ---------------------------------------------------------------------------------------------
# Unreadable metadata must not be discarded.
# ---------------------------------------------------------------------------------------------


def test_unparseable_metadata_is_preserved_verbatim(store):
    """An audit log may not lose evidence because it cannot parse it.

    Dropping the blob would leave an event that says something happened with no detail; keeping
    the raw text under `_raw` means the bytes are still there for whoever investigates.
    """
    row = (
        "evt-1",
        datetime.now(UTC).isoformat(),
        "someone@example.com",
        None,
        "auth.login",
        "success",
        None,
        None,
        "{not json",
    )
    event = audit._row_to_event(row)
    assert event.metadata == {"_raw": "{not json"}


@pytest.mark.parametrize("blank", [None, ""])
def test_absent_metadata_is_an_empty_mapping_not_a_raw_marker(store, blank):
    """No metadata and unreadable metadata are different findings; only the second needs `_raw`."""
    row = (
        "evt-2",
        datetime.now(UTC).isoformat(),
        "someone@example.com",
        None,
        "auth.login",
        "success",
        None,
        None,
        blank,
    )
    assert audit._row_to_event(row).metadata == {}


def test_readable_metadata_is_decoded(store):
    row = (
        "evt-3",
        datetime.now(UTC).isoformat(),
        "someone@example.com",
        None,
        "auth.login",
        "success",
        None,
        None,
        json.dumps({"ip": "10.0.0.1"}),
    )
    assert audit._row_to_event(row).metadata == {"ip": "10.0.0.1"}


# ---------------------------------------------------------------------------------------------
# Serialisation and export.
# ---------------------------------------------------------------------------------------------


def test_an_event_serialises_with_an_explicit_utc_timestamp(store):
    """A naive or local timestamp in an audit record makes two events impossible to order."""
    event = audit.write_audit_event(
        "auth.login",
        actor_subject="ada@example.com",
        outcome="success",
        metadata={"ip": "10.0.0.1"},
        store=store,
    )
    payload = audit.event_to_dict(event)
    assert payload["occurred_at"].endswith("+00:00")
    assert payload["actor_subject"] == "ada@example.com"
    assert payload["metadata"] == {"ip": "10.0.0.1"}


def test_export_produces_parseable_csv_with_a_header(store):
    audit.write_audit_event(
        "auth.login", actor_subject="ada@example.com", outcome="success", store=store
    )
    text = audit.export_to_string(store=store)
    rows = list(csv.reader(StringIO(text)))
    assert rows, "an export with events must not be empty"
    assert "event_type" in rows[0], "the header names the columns an auditor reads"
    assert any("ada@example.com" in cell for row in rows[1:] for cell in row)


def test_export_filters_by_event_type(store):
    audit.write_audit_event("auth.login", actor_subject="a@x.com", outcome="success", store=store)
    audit.write_audit_event("auth.logout", actor_subject="a@x.com", outcome="success", store=store)
    text = audit.export_to_string(event_type="auth.login", store=store)
    assert "auth.login" in text
    assert "auth.logout" not in text


def test_export_filters_by_time_window(store):
    old = datetime.now(UTC) - timedelta(days=30)
    audit.write_audit_event(
        "auth.login", actor_subject="old@x.com", outcome="success", occurred_at=old, store=store
    )
    audit.write_audit_event("auth.login", actor_subject="new@x.com", outcome="success", store=store)
    text = audit.export_to_string(since=datetime.now(UTC) - timedelta(days=1), store=store)
    assert "new@x.com" in text
    assert "old@x.com" not in text, "the window must exclude, or an export is always everything"


def test_an_empty_export_still_carries_its_header(store):
    """A header-only export says "no events matched". An empty string says nothing at all, and
    reads the same as a failed export."""
    text = audit.export_to_string(event_type="nothing.matches", store=store)
    assert "event_type" in text


# ---------------------------------------------------------------------------------------------
# Timestamp parsing.
# ---------------------------------------------------------------------------------------------


def test_a_naive_timestamp_is_assumed_utc():
    """The CLI takes timestamps from an operator, who will omit the offset. Assuming local time
    would shift an audit window by the server's zone and silently change what an export contains.
    """
    parsed = audit.parse_iso_timestamp("2026-08-30T12:00:00")
    assert parsed.tzinfo is UTC
    assert parsed.hour == 12


def test_an_explicit_offset_is_respected():
    parsed = audit.parse_iso_timestamp("2026-08-30T12:00:00+02:00")
    assert parsed.astimezone(UTC).hour == 10
