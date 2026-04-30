"""Tests for the portal state persistence backends and resolver."""

from __future__ import annotations

import json
import sys
import threading
from datetime import UTC
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from travel_plan_permission.http_service import PlannerProposalStore
from travel_plan_permission.persistence import (
    JsonPortalStateStore,
    SQLitePortalStateStore,
    maybe_import_legacy_state,
    resolve_portal_state_store,
)
from travel_plan_permission.persistence.resolver import (
    PORTAL_BACKEND_ENV,
    PORTAL_DATABASE_URL_ENV,
)


def _draft_payload(answers: dict[str, object]) -> dict[str, object]:
    return {
        "answers": dict(answers),
        "updated_at": "2026-01-01T00:00:00+00:00",
        "cached_artifacts": {},
        "submission_response": None,
    }


class TestSQLitePortalStateStore:
    def test_save_and_load_round_trip(self, tmp_path: Path) -> None:
        store = SQLitePortalStateStore(tmp_path / "state.sqlite3")
        store.initialize()
        snapshot = {
            "portal_drafts_by_id": {
                "abc": _draft_payload({"traveler_name": "Sam"}),
                "def": _draft_payload({"traveler_name": "Riley"}),
            },
            "review_ids_by_draft_id": {"abc": "rev-1"},
        }
        store.save_snapshot(snapshot)

        reopened = SQLitePortalStateStore(tmp_path / "state.sqlite3")
        reopened.initialize()
        loaded = reopened.load_snapshot()
        assert loaded is not None
        assert loaded["portal_drafts_by_id"]["abc"]["answers"]["traveler_name"] == "Sam"
        assert loaded["portal_drafts_by_id"]["def"]["answers"]["traveler_name"] == "Riley"
        assert loaded["review_ids_by_draft_id"] == {"abc": "rev-1"}
        store.close()
        reopened.close()

    def test_wal_journal_mode_active(self, tmp_path: Path) -> None:
        store = SQLitePortalStateStore(tmp_path / "wal-check.sqlite3")
        store.initialize()
        try:
            assert store.journal_mode() == "wal"
        finally:
            store.close()

    def test_load_returns_none_when_empty(self, tmp_path: Path) -> None:
        store = SQLitePortalStateStore(tmp_path / "empty.sqlite3")
        store.initialize()
        try:
            assert store.load_snapshot() is None
        finally:
            store.close()

    def test_per_record_upsert_preserves_other_records(self, tmp_path: Path) -> None:
        # Two store instances writing different draft ids should both survive,
        # since save_snapshot upserts per-record rather than overwriting the
        # full namespace.
        path = tmp_path / "concurrent.sqlite3"
        store_a = SQLitePortalStateStore(path)
        store_a.initialize()
        store_a.save_snapshot({"portal_drafts_by_id": {"alpha": _draft_payload({"who": "a"})}})

        store_b = SQLitePortalStateStore(path)
        store_b.initialize()
        store_b.save_snapshot({"portal_drafts_by_id": {"beta": _draft_payload({"who": "b"})}})

        loaded = SQLitePortalStateStore(path)
        loaded.initialize()
        snapshot = loaded.load_snapshot()
        assert snapshot is not None
        assert set(snapshot["portal_drafts_by_id"].keys()) == {"alpha", "beta"}
        store_a.close()
        store_b.close()
        loaded.close()

    def test_expense_drafts_use_per_record_upserts(self, tmp_path: Path) -> None:
        path = tmp_path / "expense-concurrent.sqlite3"
        store_a = SQLitePortalStateStore(path)
        store_a.initialize()
        store_a.save_snapshot({"expense_drafts_by_id": {"exp-a": _draft_payload({"who": "a"})}})

        store_b = SQLitePortalStateStore(path)
        store_b.initialize()
        store_b.save_snapshot({"expense_drafts_by_id": {"exp-b": _draft_payload({"who": "b"})}})

        loaded = SQLitePortalStateStore(path)
        loaded.initialize()
        snapshot = loaded.load_snapshot()
        assert snapshot is not None
        assert set(snapshot["expense_drafts_by_id"].keys()) == {"exp-a", "exp-b"}
        store_a.close()
        store_b.close()
        loaded.close()

    def test_threaded_writers_dont_lose_records(self, tmp_path: Path) -> None:
        path = tmp_path / "threads.sqlite3"
        bootstrap = SQLitePortalStateStore(path)
        bootstrap.initialize()
        bootstrap.close()

        errors: list[BaseException] = []

        def worker(draft_id: str) -> None:
            try:
                store = SQLitePortalStateStore(path)
                store.initialize()
                store.save_snapshot(
                    {"portal_drafts_by_id": {draft_id: _draft_payload({"id": draft_id})}}
                )
                store.close()
            except BaseException as exc:  # pragma: no cover — surfaced via assertion
                errors.append(exc)

        ids = [f"t-{i:03d}" for i in range(8)]
        threads = [threading.Thread(target=worker, args=(draft_id,)) for draft_id in ids]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors

        store = SQLitePortalStateStore(path)
        store.initialize()
        snapshot = store.load_snapshot()
        store.close()
        assert snapshot is not None
        assert set(snapshot["portal_drafts_by_id"].keys()) == set(ids)


class TestJsonPortalStateStore:
    def test_round_trip(self, tmp_path: Path) -> None:
        store = JsonPortalStateStore(tmp_path / "legacy.json", warn_on_use=False)
        store.initialize()
        store.save_snapshot({"portal_drafts_by_id": {"x": _draft_payload({"k": 1})}})
        loaded = store.load_snapshot()
        assert loaded is not None
        assert loaded["portal_drafts_by_id"]["x"]["answers"] == {"k": 1}

    def test_initialize_warns_by_default(self, tmp_path: Path) -> None:
        store = JsonPortalStateStore(tmp_path / "warn.json")
        with pytest.warns(DeprecationWarning):
            store.initialize()


class TestImporter:
    def test_imports_legacy_json_into_sqlite(self, tmp_path: Path) -> None:
        legacy = tmp_path / "portal-runtime-state.json"
        legacy.write_text(
            json.dumps(
                {
                    "portal_drafts_by_id": {"legacy": _draft_payload({"who": "history"})},
                    "review_ids_by_draft_id": {"legacy": "rev-legacy"},
                }
            ),
            encoding="utf-8",
        )

        sqlite_path = tmp_path / "portal-runtime-state.sqlite3"
        store = SQLitePortalStateStore(sqlite_path)
        store.initialize()
        assert maybe_import_legacy_state(store, legacy) is True

        snapshot = store.load_snapshot()
        store.close()
        assert snapshot is not None
        assert snapshot["portal_drafts_by_id"]["legacy"]["answers"]["who"] == "history"
        assert snapshot["review_ids_by_draft_id"] == {"legacy": "rev-legacy"}

    def test_no_op_when_sqlite_already_has_state(self, tmp_path: Path) -> None:
        legacy = tmp_path / "legacy.json"
        legacy.write_text(json.dumps({"portal_drafts_by_id": {"legacy": _draft_payload({})}}))
        sqlite_path = tmp_path / "state.sqlite3"
        store = SQLitePortalStateStore(sqlite_path)
        store.initialize()
        store.save_snapshot({"portal_drafts_by_id": {"present": _draft_payload({})}})

        assert maybe_import_legacy_state(store, legacy) is False
        snapshot = store.load_snapshot()
        store.close()
        assert snapshot is not None
        assert "legacy" not in snapshot["portal_drafts_by_id"]
        assert "present" in snapshot["portal_drafts_by_id"]

    def test_no_op_when_legacy_file_missing(self, tmp_path: Path) -> None:
        store = SQLitePortalStateStore(tmp_path / "fresh.sqlite3")
        store.initialize()
        assert maybe_import_legacy_state(store, tmp_path / "absent.json") is False
        store.close()


class TestResolver:
    def test_default_path_picks_sqlite(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(PORTAL_DATABASE_URL_ENV, raising=False)
        monkeypatch.delenv(PORTAL_BACKEND_ENV, raising=False)
        store = resolve_portal_state_store(tmp_path / "fresh.sqlite3")
        assert isinstance(store, SQLitePortalStateStore)
        store.close()

    def test_json_suffix_uses_json_backend(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(PORTAL_DATABASE_URL_ENV, raising=False)
        monkeypatch.delenv(PORTAL_BACKEND_ENV, raising=False)
        with pytest.warns(DeprecationWarning, match="TPP_PORTAL_STATE_PATH"):
            store = resolve_portal_state_store(tmp_path / "legacy.json")
        assert isinstance(store, JsonPortalStateStore)

    def test_json_suffix_deprecation_hints_sqlite_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(PORTAL_DATABASE_URL_ENV, raising=False)
        monkeypatch.delenv(PORTAL_BACKEND_ENV, raising=False)
        with pytest.warns(DeprecationWarning, match=r"\.sqlite3"):
            resolve_portal_state_store(tmp_path / "portal-runtime-state.json")

    def test_backend_env_json_emits_deprecation_warning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(PORTAL_DATABASE_URL_ENV, raising=False)
        monkeypatch.setenv(PORTAL_BACKEND_ENV, "json")
        with pytest.warns(DeprecationWarning, match="TPP_PORTAL_STATE_PATH"):
            store = resolve_portal_state_store(tmp_path / "explicit.json")
        assert isinstance(store, JsonPortalStateStore)

    def test_state_path_none_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(PORTAL_DATABASE_URL_ENV, raising=False)
        assert resolve_portal_state_store(None) is None

    def test_legacy_json_imported_on_first_sqlite_open(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(PORTAL_DATABASE_URL_ENV, raising=False)
        monkeypatch.delenv(PORTAL_BACKEND_ENV, raising=False)
        legacy = tmp_path / "portal-runtime-state.json"
        legacy.write_text(
            json.dumps({"portal_drafts_by_id": {"old": _draft_payload({"k": "v"})}}),
            encoding="utf-8",
        )
        store = resolve_portal_state_store(tmp_path / "portal-runtime-state.sqlite3")
        assert isinstance(store, SQLitePortalStateStore)
        snapshot = store.load_snapshot()
        store.close()
        assert snapshot is not None
        assert "old" in snapshot["portal_drafts_by_id"]


class TestPlannerProposalStoreOnSqlite:
    def test_drafts_round_trip_through_sqlite_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(PORTAL_DATABASE_URL_ENV, raising=False)
        monkeypatch.delenv(PORTAL_BACKEND_ENV, raising=False)
        path = tmp_path / "portal-runtime-state.sqlite3"

        first = PlannerProposalStore(state_path=path)
        draft = first.save_portal_draft({"traveler_name": "Riley"})

        second = PlannerProposalStore(state_path=path)
        restored = second.lookup_portal_draft(draft.draft_id)
        assert restored is not None
        assert restored.answers == {"traveler_name": "Riley"}

    def test_submission_response_survives_restart(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Acceptance criterion: restart preserves draft and submission response (review URL)."""
        from travel_plan_permission.policy_api import (
            PlannerCorrelationId,
            PlannerProposalOperationResponse,
        )

        monkeypatch.delenv(PORTAL_DATABASE_URL_ENV, raising=False)
        monkeypatch.delenv(PORTAL_BACKEND_ENV, raising=False)
        path = tmp_path / "portal-runtime-state.sqlite3"
        review_url = "http://localhost/portal/review/test-draft"

        first = PlannerProposalStore(state_path=path)
        draft = first.save_portal_draft({"traveler_name": "Jordan"})
        from datetime import datetime

        response = PlannerProposalOperationResponse(
            operation="submit_proposal",
            submission_status="pending",
            request_id="req-restart-test",
            correlation_id=PlannerCorrelationId(value="corr-1"),
            transport_pattern="async",
            result_payload={"review_url": review_url},
            received_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        updated = first.record_portal_submission(draft.draft_id, response)
        assert updated is not None
        assert updated.submission_response is not None

        second = PlannerProposalStore(state_path=path)
        restored = second.lookup_portal_draft(draft.draft_id)
        assert restored is not None
        assert restored.answers == {"traveler_name": "Jordan"}
        assert restored.submission_response is not None
        assert restored.submission_response.result_payload["review_url"] == review_url

    def test_legacy_json_imported_through_planner_store(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Acceptance criterion: legacy JSON is imported into SQL store on first start."""
        monkeypatch.delenv(PORTAL_DATABASE_URL_ENV, raising=False)
        monkeypatch.delenv(PORTAL_BACKEND_ENV, raising=False)
        legacy = tmp_path / "portal-runtime-state.json"
        legacy.write_text(
            json.dumps(
                {
                    "portal_drafts_by_id": {
                        "legacy-draft": _draft_payload({"traveler_name": "Legacy User"}),
                    }
                }
            ),
            encoding="utf-8",
        )

        store = PlannerProposalStore(state_path=tmp_path / "portal-runtime-state.sqlite3")
        draft = store.lookup_portal_draft("legacy-draft")
        assert draft is not None
        assert draft.answers["traveler_name"] == "Legacy User"

        second = PlannerProposalStore(state_path=tmp_path / "portal-runtime-state.sqlite3")
        draft_again = second.lookup_portal_draft("legacy-draft")
        assert draft_again is not None, "Legacy data survives on second open (not re-imported)"


class TestSQLitePortalStateStoreExtras:
    def test_path_property(self, tmp_path: Path) -> None:
        path = tmp_path / "check.sqlite3"
        store = SQLitePortalStateStore(path)
        assert store.path == path
        store.close()

    def test_close_when_never_connected(self, tmp_path: Path) -> None:
        store = SQLitePortalStateStore(tmp_path / "unused.sqlite3")
        store.close()  # must not raise

    def test_transaction_rollback_on_exception(self) -> None:
        import sqlite3

        from travel_plan_permission.persistence.sqlite_store import _transaction

        conn = sqlite3.connect(":memory:", isolation_level=None)
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT NOT NULL)")
        conn.execute("PRAGMA journal_mode=WAL")
        with pytest.raises(ValueError), _transaction(conn):
            conn.execute("INSERT INTO t VALUES (1, 'a')")
            raise ValueError("force rollback")
        row = conn.execute("SELECT * FROM t").fetchone()
        assert row is None
        conn.close()


class TestJsonPortalStateStoreExtras:
    def test_path_property(self, tmp_path: Path) -> None:
        path = tmp_path / "test.json"
        store = JsonPortalStateStore(path, warn_on_use=False)
        assert store.path == path

    def test_load_when_file_missing(self, tmp_path: Path) -> None:
        store = JsonPortalStateStore(tmp_path / "absent.json", warn_on_use=False)
        assert store.load_snapshot() is None

    def test_close_is_noop(self, tmp_path: Path) -> None:
        store = JsonPortalStateStore(tmp_path / "x.json", warn_on_use=False)
        store.close()  # must not raise


class TestImporterEdgeCases:
    def test_no_op_on_oserror(self, tmp_path: Path) -> None:
        legacy = tmp_path / "unreadable.json"
        legacy.write_text("{}")
        legacy.chmod(0o000)
        store = SQLitePortalStateStore(tmp_path / "state.sqlite3")
        store.initialize()
        try:
            result = maybe_import_legacy_state(store, legacy)
        finally:
            legacy.chmod(0o644)
        assert result is False
        store.close()

    def test_no_op_on_invalid_json(self, tmp_path: Path) -> None:
        legacy = tmp_path / "bad.json"
        legacy.write_text("not json", encoding="utf-8")
        store = SQLitePortalStateStore(tmp_path / "state.sqlite3")
        store.initialize()
        assert maybe_import_legacy_state(store, legacy) is False
        store.close()

    def test_no_op_on_empty_dict(self, tmp_path: Path) -> None:
        legacy = tmp_path / "empty.json"
        legacy.write_text("{}", encoding="utf-8")
        store = SQLitePortalStateStore(tmp_path / "state.sqlite3")
        store.initialize()
        assert maybe_import_legacy_state(store, legacy) is False
        store.close()

    def test_no_op_on_non_dict_payload(self, tmp_path: Path) -> None:
        legacy = tmp_path / "list.json"
        legacy.write_text("[]", encoding="utf-8")
        store = SQLitePortalStateStore(tmp_path / "state.sqlite3")
        store.initialize()
        assert maybe_import_legacy_state(store, legacy) is False
        store.close()


class TestResolverExtras:
    def test_coerce_sqlite_path_with_no_suffix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(PORTAL_DATABASE_URL_ENV, raising=False)
        monkeypatch.delenv(PORTAL_BACKEND_ENV, raising=False)
        path = tmp_path / "mystate"
        store = resolve_portal_state_store(path)
        assert isinstance(store, SQLitePortalStateStore)
        assert store.path.suffix == ".sqlite3"
        store.close()

    def test_coerce_sqlite_path_with_other_suffix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(PORTAL_DATABASE_URL_ENV, raising=False)
        monkeypatch.delenv(PORTAL_BACKEND_ENV, raising=False)
        path = tmp_path / "mystate.db"
        store = resolve_portal_state_store(path)
        assert isinstance(store, SQLitePortalStateStore)
        assert store.path.suffix == ".sqlite3"
        store.close()


class TestPostgresPortalStateStore:
    """Tests for PostgresPortalStateStore — psycopg mocked via sys.modules."""

    @staticmethod
    def _make_mock_psycopg() -> tuple[MagicMock, MagicMock, MagicMock]:
        mock_cur = MagicMock()
        mock_cur.__enter__ = lambda s: s
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchall.return_value = []

        mock_tx = MagicMock()
        mock_tx.__enter__ = lambda _: None
        mock_tx.__exit__ = MagicMock(return_value=False)

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_conn.transaction.return_value = mock_tx

        mock_pg = MagicMock()
        mock_pg.connect.return_value = mock_conn
        return mock_pg, mock_conn, mock_cur

    def test_missing_psycopg_raises_runtime_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "psycopg", None)

        from travel_plan_permission.persistence.postgres_store import PostgresPortalStateStore

        store = PostgresPortalStateStore("postgresql://test/db")
        with pytest.raises(RuntimeError, match="psycopg.*not installed"):
            store._connection()

    def test_initialize_creates_schema(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_pg, mock_conn, mock_cur = self._make_mock_psycopg()
        monkeypatch.setitem(sys.modules, "psycopg", mock_pg)

        from travel_plan_permission.persistence.postgres_store import PostgresPortalStateStore

        store = PostgresPortalStateStore("postgresql://test/db")
        store.initialize()
        mock_pg.connect.assert_called_once_with("postgresql://test/db", autocommit=False)
        assert mock_cur.execute.call_count >= 5
        store.close()
        assert mock_conn.close.called

    def test_load_snapshot_returns_none_when_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_pg, mock_conn, mock_cur = self._make_mock_psycopg()
        mock_cur.fetchall.return_value = []
        monkeypatch.setitem(sys.modules, "psycopg", mock_pg)

        from travel_plan_permission.persistence.postgres_store import PostgresPortalStateStore

        store = PostgresPortalStateStore("postgresql://test/db")
        assert store.load_snapshot() is None
        store.close()

    def test_load_snapshot_returns_records(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_pg, mock_conn, mock_cur = self._make_mock_psycopg()
        mock_cur.fetchall.side_effect = [
            [("portal_drafts_by_id", "abc", {"answers": {"name": "Sam"}})],
            [("review_ids_by_draft_id", '{"abc": "rev-1"}')],
        ]
        monkeypatch.setitem(sys.modules, "psycopg", mock_pg)

        from travel_plan_permission.persistence.postgres_store import PostgresPortalStateStore

        store = PostgresPortalStateStore("postgresql://test/db")
        snapshot = store.load_snapshot()
        assert snapshot is not None
        assert snapshot["portal_drafts_by_id"]["abc"]["answers"]["name"] == "Sam"
        store.close()

    def test_save_snapshot_upserts_records(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_pg, mock_conn, mock_cur = self._make_mock_psycopg()
        monkeypatch.setitem(sys.modules, "psycopg", mock_pg)

        from travel_plan_permission.persistence.postgres_store import PostgresPortalStateStore

        store = PostgresPortalStateStore("postgresql://test/db")
        store.save_snapshot(
            {
                "portal_drafts_by_id": {"d1": {"answers": {}}},
                "review_ids_by_draft_id": {"d1": "r1"},
            }
        )
        assert mock_cur.execute.call_count >= 2
        store.close()

    def test_close_when_never_connected(self) -> None:
        from travel_plan_permission.persistence.postgres_store import PostgresPortalStateStore

        store = PostgresPortalStateStore("postgresql://test/db")
        store.close()  # must not raise

    def test_resolver_uses_postgres_when_url_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_pg, mock_conn, mock_cur = self._make_mock_psycopg()
        monkeypatch.setitem(sys.modules, "psycopg", mock_pg)
        monkeypatch.setenv(PORTAL_DATABASE_URL_ENV, "postgresql://test/db")

        from travel_plan_permission.persistence.postgres_store import PostgresPortalStateStore

        store = resolve_portal_state_store(tmp_path / "ignored.sqlite3")
        assert isinstance(store, PostgresPortalStateStore)
        store.close()

    def test_database_url_property(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_pg, _, _ = self._make_mock_psycopg()
        monkeypatch.setitem(sys.modules, "psycopg", mock_pg)

        from travel_plan_permission.persistence.postgres_store import PostgresPortalStateStore

        store = PostgresPortalStateStore("postgresql://user:pass@host/mydb")
        assert store.database_url == "postgresql://user:pass@host/mydb"

    def test_cached_connection_reused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_pg, mock_conn, mock_cur = self._make_mock_psycopg()
        mock_cur.fetchall.return_value = []
        monkeypatch.setitem(sys.modules, "psycopg", mock_pg)

        from travel_plan_permission.persistence.postgres_store import PostgresPortalStateStore

        store = PostgresPortalStateStore("postgresql://test/db")
        store.initialize()
        store.load_snapshot()
        assert mock_pg.connect.call_count == 1
        store.close()

    def test_coerce_jsonb_fallthrough(self) -> None:
        from travel_plan_permission.persistence.postgres_store import _coerce_jsonb

        assert _coerce_jsonb(42) == 42
        assert _coerce_jsonb(None) is None
