"""Tests for the durable audit-event log shipped with issue #999."""

from __future__ import annotations

import csv
import io
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from travel_plan_permission import audit


@pytest.fixture
def store(tmp_path: Path) -> audit.SQLiteAuditEventStore:
    instance = audit.SQLiteAuditEventStore(tmp_path / "audit-events.sqlite3")
    instance.initialize()
    yield instance
    instance.close()


@pytest.fixture(autouse=True)
def isolated_default_store() -> None:
    """Reset the module-level default store before and after each test."""

    audit.reset_default_store()
    yield
    audit.reset_default_store()


def _event(
    event_type: str = audit.EVENT_AUTH_REQUEST,
    *,
    occurred_at: datetime | None = None,
    actor_subject: str = "alice",
    outcome: str = audit.OUTCOME_SUCCESS,
    metadata: dict[str, object] | None = None,
) -> audit.AuditEvent:
    return audit.AuditEvent(
        event_type=event_type,
        actor_subject=actor_subject,
        outcome=outcome,
        actor_role=None,
        target_kind="planner_route",
        target_id="GET /api/itineraries",
        metadata=metadata or {"foo": "bar"},
        occurred_at=occurred_at or datetime(2026, 4, 15, 12, 0, tzinfo=UTC),
    )


class TestSQLiteAuditEventStore:
    def test_write_and_query_round_trip(self, store: audit.SQLiteAuditEventStore) -> None:
        event = _event(metadata={"endpoint": "GET /api/itineraries", "n": 1})
        store.write(event)

        results = list(store.query())
        assert len(results) == 1
        retrieved = results[0]
        assert retrieved.id == event.id
        assert retrieved.event_type == audit.EVENT_AUTH_REQUEST
        assert retrieved.actor_subject == "alice"
        assert retrieved.outcome == audit.OUTCOME_SUCCESS
        assert retrieved.metadata == {"endpoint": "GET /api/itineraries", "n": 1}
        assert retrieved.occurred_at == event.occurred_at

    def test_query_filters_by_window_and_event_type(
        self, store: audit.SQLiteAuditEventStore
    ) -> None:
        store.write(_event(occurred_at=datetime(2026, 4, 1, tzinfo=UTC)))
        store.write(
            _event(
                event_type=audit.EVENT_RBAC_ROLE_CHANGE,
                occurred_at=datetime(2026, 4, 15, tzinfo=UTC),
            )
        )
        store.write(_event(occurred_at=datetime(2026, 5, 1, tzinfo=UTC)))

        windowed = list(
            store.query(
                since=datetime(2026, 4, 10, tzinfo=UTC),
                until=datetime(2026, 4, 30, tzinfo=UTC),
            )
        )
        assert [event.event_type for event in windowed] == [audit.EVENT_RBAC_ROLE_CHANGE]

        all_auth = list(store.query(event_type=audit.EVENT_AUTH_REQUEST))
        assert len(all_auth) == 2

    def test_query_results_are_ordered_ascending(self, store: audit.SQLiteAuditEventStore) -> None:
        store.write(_event(occurred_at=datetime(2026, 5, 1, tzinfo=UTC)))
        store.write(_event(occurred_at=datetime(2026, 4, 1, tzinfo=UTC)))
        store.write(_event(occurred_at=datetime(2026, 4, 15, tzinfo=UTC)))

        ordered = [event.occurred_at for event in store.query()]
        assert ordered == sorted(ordered)

    def test_prune_removes_only_strictly_older_rows(
        self, store: audit.SQLiteAuditEventStore
    ) -> None:
        store.write(_event(occurred_at=datetime(2024, 1, 1, tzinfo=UTC)))
        cutoff_event = _event(occurred_at=datetime(2025, 1, 1, tzinfo=UTC))
        store.write(cutoff_event)
        store.write(_event(occurred_at=datetime(2026, 1, 1, tzinfo=UTC)))

        removed = store.prune(datetime(2025, 1, 1, tzinfo=UTC))
        assert removed == 1

        remaining = [event.occurred_at.year for event in store.query()]
        assert remaining == [2025, 2026]


class TestWriteAuditEventHelper:
    def test_uses_default_store_when_no_explicit_store(
        self, store: audit.SQLiteAuditEventStore
    ) -> None:
        audit.set_default_store(store)
        audit.write_audit_event(
            audit.EVENT_AUTH_REQUEST,
            actor_subject="bob",
            outcome=audit.OUTCOME_FAILURE,
            metadata={"reason_code": "auth.expired"},
        )
        rows = list(store.query())
        assert len(rows) == 1
        assert rows[0].actor_subject == "bob"
        assert rows[0].metadata["reason_code"] == "auth.expired"

    def test_null_default_store_is_silent(self) -> None:
        # No default store is installed; this should not raise and not persist.
        event = audit.write_audit_event(
            audit.EVENT_AUTH_REQUEST,
            actor_subject="charlie",
            outcome=audit.OUTCOME_SUCCESS,
        )
        assert isinstance(event, audit.AuditEvent)


class TestRetentionPrune:
    def test_default_retention_is_seven_years(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(audit.RETENTION_ENV_VAR, raising=False)
        assert audit.configured_retention_days() == 365 * 7

    def test_env_override_clamps_to_positive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(audit.RETENTION_ENV_VAR, "0")
        assert audit.configured_retention_days() == 1
        monkeypatch.setenv(audit.RETENTION_ENV_VAR, "garbage")
        assert audit.configured_retention_days() == 365 * 7

    def test_prune_audit_events_uses_configured_window(
        self,
        monkeypatch: pytest.MonkeyPatch,
        store: audit.SQLiteAuditEventStore,
    ) -> None:
        monkeypatch.setenv(audit.RETENTION_ENV_VAR, "30")
        audit.set_default_store(store)
        now = datetime(2026, 4, 30, tzinfo=UTC)
        store.write(_event(occurred_at=now - timedelta(days=60)))
        store.write(_event(occurred_at=now - timedelta(days=10)))

        removed = audit.prune_audit_events(now=now)
        assert removed == 1
        assert len(list(store.query())) == 1


class TestCSVExport:
    def test_export_to_csv_filters_by_window(self, store: audit.SQLiteAuditEventStore) -> None:
        store.write(_event(occurred_at=datetime(2026, 3, 1, tzinfo=UTC)))
        store.write(
            _event(
                event_type=audit.EVENT_PROPOSAL_STATUS_CHANGE,
                occurred_at=datetime(2026, 4, 15, tzinfo=UTC),
                metadata={"to_status": "approved"},
            )
        )
        store.write(_event(occurred_at=datetime(2026, 5, 1, tzinfo=UTC)))

        buffer = io.StringIO()
        rows_written = audit.export_to_csv(
            buffer,
            since=datetime(2026, 4, 1, tzinfo=UTC),
            until=datetime(2026, 4, 30, tzinfo=UTC),
            store=store,
        )
        assert rows_written == 1
        buffer.seek(0)
        rows = list(csv.DictReader(buffer))
        assert len(rows) == 1
        assert rows[0]["event_type"] == audit.EVENT_PROPOSAL_STATUS_CHANGE
        assert "approved" in rows[0]["metadata_json"]

    def test_export_csv_header_matches_known_fields(
        self, store: audit.SQLiteAuditEventStore
    ) -> None:
        buffer = io.StringIO()
        audit.export_to_csv(buffer, store=store)
        buffer.seek(0)
        reader = csv.reader(buffer)
        header = next(reader)
        assert tuple(header) == audit.CSV_FIELDS


class TestPruneMainCLI:
    def test_prune_main_removes_events_outside_retention_window(
        self, tmp_path: Path, capfd: pytest.CaptureFixture[str]
    ) -> None:
        store_path = tmp_path / "audit.sqlite3"
        store = audit.SQLiteAuditEventStore(store_path)
        store.initialize()
        # 2019-01-01 is well beyond any reasonable retention window from "now"
        store.write(_event(occurred_at=datetime(2019, 1, 1, tzinfo=UTC)))
        store.write(_event(occurred_at=datetime(2026, 4, 28, tzinfo=UTC)))
        store.close()

        rc = audit.prune_main(["--retention-days", "365", "--store-path", str(store_path)])
        assert rc == 0
        captured = capfd.readouterr()
        assert "pruned 1 audit events" in captured.err

        store2 = audit.SQLiteAuditEventStore(store_path)
        store2.initialize()
        remaining = list(store2.query())
        store2.close()
        assert len(remaining) == 1
        assert remaining[0].occurred_at.year == 2026

    def test_prune_main_uses_default_store_path_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store_path = tmp_path / "audit.sqlite3"
        store = audit.SQLiteAuditEventStore(store_path)
        store.initialize()
        store.write(_event(occurred_at=datetime(2019, 1, 1, tzinfo=UTC)))
        store.close()

        monkeypatch.setenv(audit.AUDIT_PATH_ENV_VAR, str(store_path))
        rc = audit.prune_main(["--retention-days", "365"])
        assert rc == 0

    def test_prune_main_no_events_pruned_when_all_recent(
        self, tmp_path: Path, capfd: pytest.CaptureFixture[str]
    ) -> None:
        store_path = tmp_path / "audit.sqlite3"
        store = audit.SQLiteAuditEventStore(store_path)
        store.initialize()
        store.write(_event(occurred_at=datetime(2026, 4, 28, tzinfo=UTC)))
        store.close()

        rc = audit.prune_main(["--retention-days", "365", "--store-path", str(store_path)])
        assert rc == 0
        captured = capfd.readouterr()
        assert "pruned 0 audit events" in captured.err


class TestExportCLI:
    def test_export_main_writes_csv_for_window(
        self,
        tmp_path: Path,
        capfd: pytest.CaptureFixture[str],
    ) -> None:
        store_path = tmp_path / "audit.sqlite3"
        store = audit.SQLiteAuditEventStore(store_path)
        store.initialize()
        try:
            store.write(_event(occurred_at=datetime(2026, 4, 15, tzinfo=UTC)))
            store.write(_event(occurred_at=datetime(2026, 5, 5, tzinfo=UTC)))
        finally:
            store.close()

        out_path = tmp_path / "out.csv"
        rc = audit.export_main(
            [
                "--since",
                "2026-04-01",
                "--until",
                "2026-04-30",
                "--store-path",
                str(store_path),
                "--output",
                str(out_path),
            ]
        )
        assert rc == 0
        captured = capfd.readouterr()
        assert "exported 1 audit events" in captured.err
        rows = list(csv.DictReader(out_path.read_text(encoding="utf-8").splitlines()))
        assert len(rows) == 1

    def test_export_main_rejects_inverted_window(self, tmp_path: Path) -> None:
        store_path = tmp_path / "audit.sqlite3"
        store = audit.SQLiteAuditEventStore(store_path)
        store.initialize()
        store.close()

        with pytest.raises(SystemExit):
            audit.export_main(
                [
                    "--since",
                    "2026-04-30",
                    "--until",
                    "2026-04-01",
                    "--store-path",
                    str(store_path),
                ]
            )

    def test_export_main_returns_nonzero_when_store_missing(self, tmp_path: Path) -> None:
        rc = audit.export_main(
            [
                "--since",
                "2026-04-01",
                "--until",
                "2026-04-30",
                "--store-path",
                str(tmp_path / "missing.sqlite3"),
            ]
        )
        assert rc == 2

    def test_export_main_returns_3_on_schema_mismatch(self, tmp_path: Path) -> None:
        store_path = tmp_path / "bad.sqlite3"
        store_path.write_bytes(b"not a valid sqlite database file")

        rc = audit.export_main(
            [
                "--since",
                "2026-04-01",
                "--until",
                "2026-04-30",
                "--store-path",
                str(store_path),
            ]
        )
        assert rc == 3

    def test_export_main_returns_3_when_audit_events_columns_mismatch(self, tmp_path: Path) -> None:
        store_path = tmp_path / "bad-schema.sqlite3"
        conn = sqlite3.connect(store_path)
        try:
            conn.execute("CREATE TABLE audit_events (id TEXT PRIMARY KEY, occurred_at TEXT)")
        finally:
            conn.close()

        rc = audit.export_main(
            [
                "--since",
                "2026-04-01",
                "--until",
                "2026-04-30",
                "--store-path",
                str(store_path),
            ]
        )
        assert rc == 3

    def test_export_main_writes_to_stdout_by_default(
        self,
        tmp_path: Path,
        capfd: pytest.CaptureFixture[str],
    ) -> None:
        store_path = tmp_path / "audit.sqlite3"
        store = audit.SQLiteAuditEventStore(store_path)
        store.initialize()
        try:
            store.write(_event(occurred_at=datetime(2026, 4, 15, tzinfo=UTC)))
        finally:
            store.close()

        rc = audit.export_main(
            [
                "--since",
                "2026-04-01",
                "--until",
                "2026-04-30",
                "--store-path",
                str(store_path),
                # --output defaults to "-" (stdout)
            ]
        )
        assert rc == 0
        captured = capfd.readouterr()
        assert "event_type" in captured.out

    def test_export_main_warns_on_unknown_event_type(
        self,
        tmp_path: Path,
        capfd: pytest.CaptureFixture[str],
    ) -> None:
        store_path = tmp_path / "audit.sqlite3"
        store = audit.SQLiteAuditEventStore(store_path)
        store.initialize()
        store.close()

        rc = audit.export_main(
            [
                "--since",
                "2026-04-01",
                "--until",
                "2026-04-30",
                "--store-path",
                str(store_path),
                "--event-type",
                "unknown.custom_type",
            ]
        )
        assert rc == 0
        captured = capfd.readouterr()
        assert "warning" in captured.err
        assert "unknown.custom_type" in captured.err


class TestEmitPoints:
    """Integration checks that the listed boundaries write durable events."""

    def test_mint_bootstrap_token_emits_audit_event(
        self, store: audit.SQLiteAuditEventStore
    ) -> None:
        from travel_plan_permission import planner_auth

        audit.set_default_store(store)
        token = planner_auth.mint_bootstrap_token(
            subject="trip-planner-local",
            permissions=(planner_auth.Permission.VIEW, planner_auth.Permission.CREATE),
            provider="azure_ad",
            secret="x" * 32,
            expires_in_seconds=300,
        )
        assert token

        rows = list(store.query(event_type=audit.EVENT_AUTH_BOOTSTRAP_MINT))
        assert len(rows) == 1
        assert rows[0].actor_subject == "trip-planner-local"
        assert rows[0].metadata["provider"] == "azure_ad"
        assert rows[0].metadata["audience"] == "planner-service"

    def test_authenticate_request_failure_emits_failure_event(
        self,
        store: audit.SQLiteAuditEventStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from travel_plan_permission import planner_auth

        audit.set_default_store(store)
        monkeypatch.setenv("TPP_BASE_URL", "https://tpp.example/")
        monkeypatch.setenv("TPP_OIDC_PROVIDER", "azure_ad")
        monkeypatch.setenv("TPP_AUTH_MODE", "static-token")
        monkeypatch.setenv("TPP_ACCESS_TOKEN", "secret-token")
        monkeypatch.setenv("TPP_OIDC_ISSUER", "https://login.microsoftonline.com/tenant/v2.0")
        monkeypatch.setenv(
            "TPP_OIDC_JWKS_URL",
            "https://login.microsoftonline.com/common/discovery/v2.0/keys",
        )
        monkeypatch.setenv("TPP_OIDC_AUDIENCE", "planner-service")

        config = planner_auth.PlannerAuthConfig.from_env()
        with pytest.raises(PermissionError):
            planner_auth.authenticate_request(
                "Bearer wrong-token",
                config=config,
                required_permission=planner_auth.Permission.VIEW,
                route="GET /api/itineraries",
            )

        rows = list(store.query(event_type=audit.EVENT_AUTH_REQUEST))
        assert len(rows) == 1
        assert rows[0].outcome == audit.OUTCOME_FAILURE
        assert rows[0].metadata["reason_code"] == "auth.invalid_bearer"
        assert rows[0].metadata["auth_mode"] == "static-token"
        assert rows[0].target_id == "GET /api/itineraries"

    def test_authenticate_request_success_emits_success_event(
        self,
        store: audit.SQLiteAuditEventStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from travel_plan_permission import planner_auth

        audit.set_default_store(store)
        monkeypatch.setenv("TPP_BASE_URL", "https://tpp.example/")
        monkeypatch.setenv("TPP_OIDC_PROVIDER", "azure_ad")
        monkeypatch.setenv("TPP_AUTH_MODE", "static-token")
        monkeypatch.setenv("TPP_ACCESS_TOKEN", "secret-token")
        monkeypatch.setenv("TPP_OIDC_ISSUER", "https://login.microsoftonline.com/tenant/v2.0")
        monkeypatch.setenv(
            "TPP_OIDC_JWKS_URL",
            "https://login.microsoftonline.com/common/discovery/v2.0/keys",
        )
        monkeypatch.setenv("TPP_OIDC_AUDIENCE", "planner-service")
        config = planner_auth.PlannerAuthConfig.from_env()

        context = planner_auth.authenticate_request(
            "Bearer secret-token",
            config=config,
            required_permission=planner_auth.Permission.VIEW,
            route="GET /api/itineraries",
        )
        assert context.subject  # sanity

        rows = list(store.query(event_type=audit.EVENT_AUTH_REQUEST))
        assert len(rows) == 1
        assert rows[0].outcome == audit.OUTCOME_SUCCESS
        assert rows[0].target_id == "GET /api/itineraries"
        assert rows[0].metadata["auth_mode"] == "static-token"

    def test_authenticate_request_known_subject_failure_records_subject(
        self,
        store: audit.SQLiteAuditEventStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from travel_plan_permission import planner_auth

        audit.set_default_store(store)
        monkeypatch.setenv("TPP_BASE_URL", "https://tpp.example/")
        monkeypatch.setenv("TPP_OIDC_PROVIDER", "azure_ad")
        monkeypatch.setenv("TPP_AUTH_MODE", "static-token")
        monkeypatch.setenv("TPP_ACCESS_TOKEN", "secret-token")

        config = planner_auth.PlannerAuthConfig.from_env()
        with pytest.raises(PermissionError):
            planner_auth.authenticate_request(
                "Bearer secret-token",
                config=config,
                required_permission=planner_auth.Permission.APPROVE,
                route="POST /portal/manager/reviews/{review_id}/decision",
            )

        rows = list(store.query(event_type=audit.EVENT_AUTH_REQUEST))
        assert len(rows) == 1
        assert rows[0].outcome == audit.OUTCOME_FAILURE
        assert rows[0].actor_subject == "planner-static-client"
        assert rows[0].metadata["reason_code"] == "auth.insufficient_permission"
        assert rows[0].metadata["permissions"] == ["view", "create"]
        assert rows[0].target_id == "POST /portal/manager/reviews/{review_id}/decision"

    def test_authenticate_request_config_error_emits_failure_event(
        self,
        store: audit.SQLiteAuditEventStore,
    ) -> None:
        from travel_plan_permission import planner_auth

        audit.set_default_store(store)
        # Build a config that is not ready (auth_mode is None → config.is_ready is False)
        config = planner_auth.PlannerAuthConfig(
            base_url="https://tpp.example/",
            oidc_provider="google",
            auth_mode=None,
            access_token_configured=False,
            bootstrap_secret_configured=False,
            bootstrap_ttl_seconds=900,
            oidc_audience=None,
            oidc_role_map_configured=False,
            oidc_subject_claim="sub",
            missing_config=("TPP_AUTH_MODE",),
            invalid_config=(),
        )

        with pytest.raises(ValueError, match="not ready"):
            planner_auth.authenticate_request(
                "Bearer some-token",
                config=config,
                required_permission=planner_auth.Permission.VIEW,
                route="GET /planner/policy/snapshot",
            )

        rows = list(store.query(event_type=audit.EVENT_AUTH_REQUEST))
        assert len(rows) == 1
        assert rows[0].outcome == audit.OUTCOME_FAILURE
        assert rows[0].metadata["reason_code"] == "config.not_ready"
        assert rows[0].metadata["auth_mode"] == "unconfigured"
        assert rows[0].target_id == "GET /planner/policy/snapshot"

    def test_role_change_request_emits_event(self, store: audit.SQLiteAuditEventStore) -> None:
        from travel_plan_permission.security import RoleName, SecurityModel

        audit.set_default_store(store)
        model = SecurityModel()
        request = model.request_role_change("alice", "bob", RoleName.APPROVER)

        rows = list(store.query(event_type=audit.EVENT_RBAC_ROLE_CHANGE))
        assert len(rows) == 1
        assert rows[0].actor_subject == "alice"
        assert rows[0].target_id == "bob"
        assert rows[0].metadata["transition"] == "requested"
        assert rows[0].metadata["request_id"] == request.request_id

    def test_role_change_approve_emits_event(self, store: audit.SQLiteAuditEventStore) -> None:
        from travel_plan_permission.security import RoleName, SecurityModel

        audit.set_default_store(store)
        model = SecurityModel()
        request = model.request_role_change("alice", "bob", RoleName.APPROVER)
        model.approve_role_change("admin", RoleName.SYSTEM_ADMIN, request.request_id)

        approvals = [
            row
            for row in store.query(event_type=audit.EVENT_RBAC_ROLE_CHANGE)
            if row.metadata.get("transition") == "approved"
        ]
        assert len(approvals) == 1
        assert approvals[0].actor_role == RoleName.SYSTEM_ADMIN.value

    def test_proposal_status_change_emits_from_to_status(
        self, store: audit.SQLiteAuditEventStore
    ) -> None:
        from decimal import Decimal

        from travel_plan_permission.http_service import PlannerProposalStore
        from travel_plan_permission.models import TripPlan
        from travel_plan_permission.policy_api import (
            PlannerPolicySnapshot,
            PolicyCheckResult,
        )
        from travel_plan_permission.review_workflow import ReviewAction, ReviewStatus

        audit.set_default_store(store)

        trip = TripPlan(
            trip_id="T-001",
            traveler_name="Alice",
            destination="New York",
            departure_date=datetime(2026, 5, 1, tzinfo=UTC).date(),
            return_date=datetime(2026, 5, 5, tzinfo=UTC).date(),
            purpose="Conference",
            estimated_cost=Decimal("1500.00"),
        )
        policy_result = PolicyCheckResult(status="pass", issues=[], policy_version="v1")
        from travel_plan_permission.policy_api import PlannerAuthContract, PlannerVersionContract

        policy_snapshot = PlannerPolicySnapshot(
            trip_id="T-001",
            freshness="current",
            generated_at=datetime(2026, 4, 30, tzinfo=UTC),
            expires_at=datetime(2026, 5, 30, tzinfo=UTC),
            policy_status="pass",
            auth=PlannerAuthContract(
                endpoint="/planner/policy/snapshot",
                required_permission="view",
                auth_scheme="bearer",
            ),
            versioning=PlannerVersionContract(
                contract_version="1.0",
                policy_version="v1",
                compatible_with_planner_cache=True,
                etag="abc123",
            ),
        )

        proposal_store = PlannerProposalStore()
        review = proposal_store.manager_reviews.create_or_get(
            draft_id="draft-001",
            trip_plan=trip,
            policy_snapshot=policy_snapshot,
            policy_result=policy_result,
        )
        assert review.status == ReviewStatus.PENDING_MANAGER_REVIEW

        proposal_store.apply_manager_review_action(
            review.review_id,
            action=ReviewAction.APPROVE,
            actor_id="manager-alice",
            rationale="Approved per budget policy.",
        )

        rows = list(store.query(event_type=audit.EVENT_PROPOSAL_STATUS_CHANGE))
        assert len(rows) == 1
        row = rows[0]
        assert row.outcome == ReviewStatus.APPROVED.value
        assert row.metadata["from_status"] == ReviewStatus.PENDING_MANAGER_REVIEW.value
        assert row.metadata["to_status"] == ReviewStatus.APPROVED.value
        assert row.target_kind == "manager_review"
        assert row.target_id == review.review_id
