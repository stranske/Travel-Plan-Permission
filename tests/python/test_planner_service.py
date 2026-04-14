from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from travel_plan_permission.planner_service import PlannerServiceStore, create_app

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "planner_integration"


def _fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def test_healthcheck_lists_planner_routes() -> None:
    client = TestClient(create_app(PlannerServiceStore.with_demo_seed()))

    response = client.get("/healthz")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert "/api/planner/policy-snapshot" in payload["planner_routes"]


def test_readiness_reports_missing_runtime_config(monkeypatch) -> None:
    for key in ("TPP_BASE_URL", "TPP_ACCESS_TOKEN", "TPP_OIDC_PROVIDER"):
        monkeypatch.delenv(key, raising=False)

    client = TestClient(create_app(PlannerServiceStore.with_demo_seed()))
    response = client.get("/readyz")

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["ok"] is False
    assert detail["missing_config"] == [
        "TPP_BASE_URL",
        "TPP_ACCESS_TOKEN",
        "TPP_OIDC_PROVIDER",
    ]
    assert detail["seeded_trip_ids"] == ["TRIP-PLANNER-2001"]


def test_snapshot_route_returns_documented_contract_shape() -> None:
    client = TestClient(create_app(PlannerServiceStore.with_demo_seed()))

    response = client.request(
        "GET",
        "/api/planner/policy-snapshot",
        json=_fixture("policy_snapshot_request.json"),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["trip_id"] == "TRIP-PLANNER-2001"
    assert payload["auth"]["endpoint"] == "GET /api/planner/policy-snapshot"
    assert payload["versioning"]["contract_version"] == "2026-04-11"


def test_submission_status_and_evaluation_routes_share_stored_trip_state() -> None:
    client = TestClient(create_app(PlannerServiceStore.with_demo_seed()))
    trip_plan = _fixture("proposal_submission.json")
    submission_request = {
        "trip_id": "TRIP-PLANNER-2001",
        "proposal_id": "proposal-123",
        "proposal_version": "proposal-v1",
        "payload": {
            "selected_options": ["flight-1", "hotel-3"],
            "submission_mode": "queue",
        },
        "request_id": "req-submit-001",
        "correlation_id": {
            "value": "corr-submit-001",
            "issued_by": "trip-planner",
        },
        "transport_pattern": "deferred",
        "organization_id": "org-acme",
        "submitted_at": "2026-04-11T12:30:00Z",
        "service_available": True,
    }

    submit_response = client.post(
        "/api/planner/proposals",
        json={
            "trip_plan": trip_plan,
            "request": submission_request,
        },
    )

    assert submit_response.status_code == 202
    submit_payload = submit_response.json()
    execution_id = submit_payload["result_payload"]["execution_id"]
    assert submit_payload["status_endpoint"].endswith(execution_id)

    status_response = client.request(
        "GET",
        f"/api/planner/proposals/proposal-123/executions/{execution_id}",
        json={
            "trip_id": "TRIP-PLANNER-2001",
            "proposal_id": "proposal-123",
            "proposal_version": "proposal-v1",
            "execution_id": execution_id,
            "request_id": "req-status-001",
            "correlation_id": {
                "value": "corr-submit-001",
                "issued_by": "trip-planner",
            },
            "transport_pattern": "deferred",
            "requested_at": "2026-04-11T12:31:00Z",
            "service_available": True,
        },
    )

    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["operation"] == "poll_execution_status"
    assert status_payload["result_payload"]["trip_id"] == "TRIP-PLANNER-2001"

    evaluation_response = client.request(
        "GET",
        f"/api/planner/executions/{execution_id}/evaluation-result",
        json={
            "trip_id": "TRIP-PLANNER-2001",
            "proposal_id": "proposal-123",
            "proposal_version": "proposal-v1",
            "execution_id": execution_id,
            "request_id": "req-eval-001",
            "correlation_id": {
                "value": "corr-submit-001",
                "issued_by": "trip-planner",
            },
            "requested_at": "2026-04-11T12:32:00Z",
        },
    )

    assert evaluation_response.status_code == 200
    evaluation_payload = evaluation_response.json()
    assert evaluation_payload["execution_id"] == execution_id
    assert evaluation_payload["status_endpoint"].endswith(execution_id)
    assert evaluation_payload["policy_result"]["status"] in {"pass", "fail"}
