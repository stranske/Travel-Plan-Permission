from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from travel_plan_permission.http_service import (
    PlannerProposalStore,
    PlannerRuntimeConfigError,
    create_app,
    main,
)
from travel_plan_permission.planner_auth import mint_bootstrap_token
from travel_plan_permission.policy_api import PlannerProposalOperationResponse
from travel_plan_permission.security import Permission

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "planner_integration"
AUTH_HEADER = {"Authorization": "Bearer dev-token"}


def _load_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def _set_runtime_env(monkeypatch, *, provider: str = "google") -> None:
    monkeypatch.setenv("TPP_BASE_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("TPP_OIDC_PROVIDER", provider)
    monkeypatch.setenv("TPP_AUTH_MODE", "static-token")
    monkeypatch.setenv("TPP_ACCESS_TOKEN", "dev-token")


def _set_bootstrap_runtime_env(monkeypatch, *, provider: str = "google") -> None:
    monkeypatch.setenv("TPP_BASE_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("TPP_OIDC_PROVIDER", provider)
    monkeypatch.setenv("TPP_AUTH_MODE", "bootstrap-token")
    monkeypatch.setenv("TPP_BOOTSTRAP_SIGNING_SECRET", "bootstrap-secret-123")


def test_readyz_reports_missing_runtime_config(monkeypatch) -> None:
    monkeypatch.delenv("TPP_BASE_URL", raising=False)
    monkeypatch.delenv("TPP_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("TPP_OIDC_PROVIDER", raising=False)
    monkeypatch.delenv("TPP_AUTH_MODE", raising=False)
    monkeypatch.delenv("TPP_BOOTSTRAP_SIGNING_SECRET", raising=False)

    client = TestClient(create_app())

    response = client.get("/readyz")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "misconfigured"
    assert payload["config"]["missing_config"] == [
        "TPP_BASE_URL",
        "TPP_OIDC_PROVIDER",
        "TPP_AUTH_MODE",
    ]
    assert payload["config"]["invalid_config"] == []


def test_snapshot_route_returns_planner_contract(monkeypatch) -> None:
    _set_runtime_env(monkeypatch)

    client = TestClient(create_app())
    trip_plan = _load_fixture("proposal_submission.json")
    snapshot_request = _load_fixture("policy_snapshot_request.json")

    response = client.request(
        "GET",
        "/api/planner/policy-snapshot",
        headers=AUTH_HEADER,
        json={"trip_plan": trip_plan, "request": snapshot_request},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["trip_id"] == snapshot_request["trip_id"]
    assert payload["auth"]["endpoint"] == "GET /api/planner/policy-snapshot"
    assert payload["versioning"]["planner_known_policy_version"] == "d7a6d25a"


def test_submission_status_and_evaluation_routes_round_trip(monkeypatch) -> None:
    _set_runtime_env(monkeypatch, provider="okta")

    client = TestClient(create_app(PlannerProposalStore()))
    trip_plan = _load_fixture("proposal_submission.json")
    request_payload = {
        "trip_id": trip_plan["trip_id"],
        "proposal_id": "proposal-123",
        "proposal_version": "proposal-v1",
        "payload": {"selected_options": ["flight-1", "hotel-3"]},
    }

    submit_response = client.post(
        "/api/planner/proposals",
        headers=AUTH_HEADER,
        json={"trip_plan": trip_plan, "request": request_payload},
    )

    assert submit_response.status_code == 200
    submit_payload = submit_response.json()
    submit_contract = PlannerProposalOperationResponse.model_validate(submit_payload)
    execution_id = str(submit_contract.result_payload["execution_id"])

    status_response = client.get(
        f"/api/planner/proposals/proposal-123/executions/{execution_id}",
        headers=AUTH_HEADER,
    )
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["operation"] == "poll_execution_status"
    assert status_payload["result_payload"]["execution_id"] == execution_id

    evaluation_response = client.get(
        f"/api/planner/executions/{execution_id}/evaluation-result",
        headers=AUTH_HEADER,
    )
    assert evaluation_response.status_code == 200
    evaluation_payload = evaluation_response.json()
    assert evaluation_payload["execution_id"] == execution_id
    assert evaluation_payload["status_endpoint"].endswith(
        f"/proposal-123/executions/{execution_id}"
    )


def test_readyz_reports_invalid_oidc_provider(monkeypatch) -> None:
    _set_runtime_env(monkeypatch, provider="github")

    client = TestClient(create_app())

    response = client.get("/readyz")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "misconfigured"
    assert payload["config"]["missing_config"] == []
    assert payload["config"]["invalid_config"] == ["TPP_OIDC_PROVIDER"]


def test_planner_routes_require_bearer_token(monkeypatch) -> None:
    _set_runtime_env(monkeypatch)
    client = TestClient(create_app())
    trip_plan = _load_fixture("proposal_submission.json")
    snapshot_request = _load_fixture("policy_snapshot_request.json")

    missing = client.request(
        "GET",
        "/api/planner/policy-snapshot",
        json={"trip_plan": trip_plan, "request": snapshot_request},
    )
    invalid = client.request(
        "GET",
        "/api/planner/policy-snapshot",
        headers={"Authorization": "Bearer nope"},
        json={"trip_plan": trip_plan, "request": snapshot_request},
    )

    assert missing.status_code == 401
    assert missing.json()["detail"] == "Missing bearer token."
    assert invalid.status_code == 403
    assert invalid.json()["detail"] == "Invalid bearer token."


def test_bootstrap_token_allows_planner_routes(monkeypatch) -> None:
    _set_bootstrap_runtime_env(monkeypatch)
    client = TestClient(create_app())
    trip_plan = _load_fixture("proposal_submission.json")
    snapshot_request = _load_fixture("policy_snapshot_request.json")
    token = mint_bootstrap_token(
        subject="trip-planner-preview",
        permissions=(Permission.VIEW, Permission.CREATE),
        provider="google",
        secret="bootstrap-secret-123",
        expires_in_seconds=600,
    )

    response = client.request(
        "GET",
        "/api/planner/policy-snapshot",
        headers={"Authorization": f"Bearer {token}"},
        json={"trip_plan": trip_plan, "request": snapshot_request},
    )

    assert response.status_code == 200


def test_bootstrap_token_rejects_missing_create_permission(monkeypatch) -> None:
    _set_bootstrap_runtime_env(monkeypatch)
    client = TestClient(create_app())
    trip_plan = _load_fixture("proposal_submission.json")
    token = mint_bootstrap_token(
        subject="trip-planner-preview",
        permissions=(Permission.VIEW,),
        provider="google",
        secret="bootstrap-secret-123",
        expires_in_seconds=600,
    )
    request_payload = {
        "trip_id": trip_plan["trip_id"],
        "proposal_id": "proposal-123",
        "proposal_version": "proposal-v1",
        "payload": {"selected_options": ["flight-1", "hotel-3"]},
    }

    response = client.post(
        "/api/planner/proposals",
        headers={"Authorization": f"Bearer {token}"},
        json={"trip_plan": trip_plan, "request": request_payload},
    )

    assert response.status_code == 403
    assert "does not grant 'create'" in response.json()["detail"]


def test_main_fails_fast_when_runtime_is_misconfigured(monkeypatch) -> None:
    monkeypatch.delenv("TPP_BASE_URL", raising=False)
    monkeypatch.delenv("TPP_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("TPP_OIDC_PROVIDER", raising=False)
    monkeypatch.delenv("TPP_AUTH_MODE", raising=False)
    monkeypatch.delenv("TPP_BOOTSTRAP_SIGNING_SECRET", raising=False)

    try:
        main([])
    except PlannerRuntimeConfigError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected PlannerRuntimeConfigError")

    assert "missing:" in message
    assert "TPP_AUTH_MODE" in message


def test_snapshot_route_returns_bad_request_for_contract_mismatch(monkeypatch) -> None:
    _set_runtime_env(monkeypatch)
    client = TestClient(create_app())
    trip_plan = _load_fixture("proposal_submission.json")
    snapshot_request = _load_fixture("policy_snapshot_request.json")
    snapshot_request["trip_id"] = "trip-mismatch"

    response = client.request(
        "GET",
        "/api/planner/policy-snapshot",
        headers=AUTH_HEADER,
        json={"trip_plan": trip_plan, "request": snapshot_request},
    )

    assert response.status_code == 400
    assert "trip_id" in response.json()["detail"]
