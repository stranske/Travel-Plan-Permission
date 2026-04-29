"""Tests for the portal state persistence backends and resolver."""

from __future__ import annotations

import json
import threading
from pathlib import Path

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
        assert (
            loaded["portal_drafts_by_id"]["def"]["answers"]["traveler_name"] == "Riley"
        )
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
        store_a.save_snapshot(
            {"portal_drafts_by_id": {"alpha": _draft_payload({"who": "a"})}}
        )

        store_b = SQLitePortalStateStore(path)
        store_b.initialize()
        store_b.save_snapshot(
            {"portal_drafts_by_id": {"beta": _draft_payload({"who": "b"})}}
        )

        loaded = SQLitePortalStateStore(path)
        loaded.initialize()
        snapshot = loaded.load_snapshot()
        assert snapshot is not None
        assert set(snapshot["portal_drafts_by_id"].keys()) == {"alpha", "beta"}
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
                    {
                        "portal_drafts_by_id": {
                            draft_id: _draft_payload({"id": draft_id})
                        }
                    }
                )
                store.close()
            except BaseException as exc:  # pragma: no cover — surfaced via assertion
                errors.append(exc)

        ids = [f"t-{i:03d}" for i in range(8)]
        threads = [
            threading.Thread(target=worker, args=(draft_id,)) for draft_id in ids
        ]
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
                    "portal_drafts_by_id": {
                        "legacy": _draft_payload({"who": "history"})
                    },
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
        legacy.write_text(
            json.dumps({"portal_drafts_by_id": {"legacy": _draft_payload({})}})
        )
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
        store = resolve_portal_state_store(tmp_path / "legacy.json")
        assert isinstance(store, JsonPortalStateStore)

    def test_state_path_none_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
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
