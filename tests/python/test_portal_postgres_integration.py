"""Production-service parity and real PostgreSQL acceptance on isolated databases."""

from __future__ import annotations

import os
import threading
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from travel_plan_permission.http_service import PlannerProposalStore
from travel_plan_permission.models import TripPlan
from travel_plan_permission.persistence import SQLitePortalStateStore
from travel_plan_permission.persistence.postgres_store import PostgresPortalStateStore
from travel_plan_permission.policy_api import (
    PlannerCorrelationId,
    PlannerProposalOperationResponse,
    PlannerProposalSubmissionRequest,
)


@pytest.fixture(params=["sqlite", "postgres"])
def service_factory(request, tmp_path, monkeypatch):
    """Never touch an existing database: the real-server arm creates its own."""
    stores = []
    admin = None
    name = None
    database_url = None
    if request.param == "postgres":
        admin_url = os.getenv("TPP_TEST_POSTGRES_ADMIN_URL")
        if not admin_url:
            pytest.skip("Set TPP_TEST_POSTGRES_ADMIN_URL for the real-server arm")
        # A requested real-server run must fail if the driver/server is unavailable.
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo

        admin = psycopg.connect(admin_url, autocommit=True, connect_timeout=5)
        name = "tpp_test_" + uuid4().hex
        try:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        except BaseException:
            admin.close()
            raise
        database_url = make_conninfo(admin_url, dbname=name, connect_timeout=5)
        monkeypatch.setenv("TPP_PORTAL_DATABASE_URL", database_url)
    else:
        monkeypatch.delenv("TPP_PORTAL_DATABASE_URL", raising=False)
    monkeypatch.delenv("TPP_PORTAL_BACKEND", raising=False)

    def create():
        # Exercise the production environment resolver, not a directly injected mock.
        service = PlannerProposalStore(state_path=tmp_path / "portal.sqlite3")
        assert isinstance(
            service.store,
            PostgresPortalStateStore if database_url else SQLitePortalStateStore,
        )
        stores.append(service)
        return service

    try:
        yield create
    finally:
        for service in stores:
            service.close()
        if admin is not None:
            try:
                admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            finally:
                admin.close()


def test_real_services_refresh_peer_drafts_and_preserve_restart(service_factory):
    first, second = service_factory(), service_factory()
    draft_a = first.save_portal_draft({"traveler_name": "first"})
    peer = second.lookup_portal_draft(draft_a.draft_id)
    assert peer is not None and peer.answers["traveler_name"] == "first"
    draft_b = second.save_portal_draft({"traveler_name": "second"})
    peer = first.lookup_portal_draft(draft_b.draft_id)
    assert peer is not None and peer.answers["traveler_name"] == "second"
    first.close()
    second.close()
    reopened = service_factory()
    assert set(reopened.portal_drafts_by_id) == {draft_a.draft_id, draft_b.draft_id}


def test_real_service_proposal_roundtrip_and_peer_readback(service_factory):
    first, peer = service_factory(), service_factory()
    trip = TripPlan(
        trip_id="postgres-acceptance",
        traveler_name="Test traveler",
        destination="Chicago",
        departure_date="2026-10-05",
        return_date="2026-10-06",
        purpose="Integration test",
        estimated_cost="100.00",
    )
    request = PlannerProposalSubmissionRequest(
        trip_id=trip.trip_id, proposal_id="proposal-test", proposal_version="v1"
    )
    response = PlannerProposalOperationResponse(
        operation="submit_proposal",
        submission_status="pending",
        request_id="request-test",
        correlation_id=PlannerCorrelationId(value="correlation-test"),
        transport_pattern="async",
        result_payload={"execution_id": "execution-test", "review_url": "/review/test"},
        received_at=datetime(2026, 10, 4, tzinfo=UTC),
    )
    first.record_submission(trip, request, response)
    stored = peer.lookup_submission("execution-test")
    assert stored is not None
    assert stored.trip_plan == trip
    assert stored.request == request
    assert stored.response == response
    first.close()
    peer.close()
    reopened = service_factory()
    assert reopened.lookup_submission("execution-test") == stored
    assert reopened.lookup_trip_plan(trip.trip_id) == trip


def test_real_independent_services_preserve_concurrent_writers(service_factory):
    first, second = service_factory(), service_factory()
    barrier = threading.Barrier(2)
    errors, ids = [], []

    def write(service, prefix):
        try:
            barrier.wait(timeout=5)
            for index in range(5):
                draft = service.save_portal_draft({"traveler_name": f"{prefix}-{index}"})
                ids.append(draft.draft_id)
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=write, args=(first, "first")),
        threading.Thread(target=write, args=(second, "second")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert all(not thread.is_alive() for thread in threads), "service lock failed to release"
    assert not errors, errors
    first.close()
    second.close()
    reopened = service_factory()
    assert len(ids) == 10 and set(reopened.portal_drafts_by_id) == set(ids)
