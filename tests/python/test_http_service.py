from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from travel_plan_permission import audit, http_service, planner_auth, portal_review
from travel_plan_permission.http_service import (
    PlannerProposalStore,
    PortalArtifact,
    create_app,
    main,
)
from travel_plan_permission.planner_auth import mint_bootstrap_token
from travel_plan_permission.policy_api import PlannerProposalOperationResponse
from travel_plan_permission.security import AuditEventType, Permission

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


def _set_oidc_runtime_env(monkeypatch) -> None:
    monkeypatch.setenv("TPP_BASE_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("TPP_OIDC_PROVIDER", "google")
    monkeypatch.setenv("TPP_AUTH_MODE", "oidc")
    monkeypatch.setenv("TPP_OIDC_AUDIENCE", "trip-planner")
    monkeypatch.setenv("TPP_OIDC_ISSUER", "https://accounts.google.com")
    monkeypatch.setenv("TPP_OIDC_JWKS_URL", "https://issuer.example/jwks.json")


def _build_oidc_token_and_jwks(*, audience: str = "trip-planner") -> tuple[str, dict[str, object]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk.update({"kid": "planner-key", "alg": "RS256", "use": "sig"})
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "iss": "https://accounts.google.com",
            "aud": audience,
            "sub": "planner@example.com",
            "exp": now + timedelta(minutes=10),
            "nbf": now - timedelta(seconds=5),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "planner-key"},
    )
    return token, {"keys": [jwk]}


def _oidc_auth_header(monkeypatch, *, audience: str = "trip-planner") -> dict[str, str]:
    planner_auth._JWKS_CACHE.clear()
    token, jwks = _build_oidc_token_and_jwks(audience=audience)
    monkeypatch.setattr(
        planner_auth,
        "_fetch_jwks_document",
        lambda _url: jwks,
    )
    return {"Authorization": f"Bearer {token}"}


@contextmanager
def _serve_jwks(document: dict[str, object]) -> Iterator[str]:
    payload = json.dumps(document).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib hook name
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/jwks.json"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def _bootstrap_auth_header(
    *,
    subject: str,
    permissions: tuple[Permission, ...],
    provider: str = "google",
) -> dict[str, str]:
    token = mint_bootstrap_token(
        subject=subject,
        permissions=permissions,
        provider=provider,
        secret="bootstrap-secret-123",
        expires_in_seconds=600,
    )
    return {"Authorization": f"Bearer {token}"}


def _create_portal_draft(
    client: TestClient,
    *,
    payload: dict[str, str] | None = None,
) -> tuple[str, str]:
    response = client.post(
        "/portal/draft",
        data=payload or _portal_form_payload(),
        follow_redirects=False,
    )

    assert response.status_code == 303
    location = response.headers["location"]
    match = re.search(r"/portal/review/([^/]+)$", location)
    assert match is not None
    return match.group(1), location


def _get_portal_review(
    client: TestClient,
    draft_id: str,
    *,
    headers: dict[str, str] | None = None,
):
    return client.get(
        f"/portal/review/{draft_id}",
        headers=headers or AUTH_HEADER,
        follow_redirects=True,
    )


def _portal_form_payload() -> dict[str, str]:
    return {
        "traveler_name": "Alex Rivera",
        "business_purpose": "Regional partner summit",
        "cost_center": "OPS-410",
        "city_state": "Seattle, WA",
        "destination_zip": "98101",
        "depart_date": "2025-10-05",
        "return_date": "2025-10-09",
        "notes": "Request airport pickup and late checkout.",
        "flight_pref_outbound.carrier_flight": "AS120",
        "flight_pref_outbound.depart_time": "2025-10-05T07:15",
        "flight_pref_outbound.arrive_time": "2025-10-05T09:40",
        "flight_pref_outbound.roundtrip_cost": "455.25",
        "flight_pref_return.carrier_flight": "AS221",
        "flight_pref_return.depart_time": "2025-10-09T18:10",
        "flight_pref_return.arrive_time": "2025-10-09T20:30",
        "lowest_cost_roundtrip": "430.00",
        "hotel.name": "Pine Street Suites",
        "hotel.address": "120 Pine St",
        "hotel.city_state": "Seattle, WA",
        "hotel.nightly_rate": "210.00",
        "hotel.nights": "4",
        "hotel.conference_hotel": "true",
        "hotel.price_compare_notes": "Conference hotel is $20 more per night.",
        "comparable_hotels[0].name": "Marketview Hotel",
        "comparable_hotels[0].nightly_rate": "190.00",
        "ground_transport_pref": "rideshare/taxi",
        "parking_estimate": "35.00",
        "event_registration_cost": "320.00",
        "booking_date": "2025-09-20",
        "selected_fare": "455.25",
        "lowest_fare": "430.00",
        "cabin_class": "economy",
        "flight_duration_hours": "2.5",
        "fare_evidence_attached": "true",
        "driving_cost": "120.00",
        "flight_cost": "200.00",
        "distance_from_office_miles": "12.5",
        "overnight_stay": "true",
        "meals_provided": "false",
        "meal_per_diem_requested": "true",
    }


def _expense_form_payload() -> dict[str, str]:
    return {
        "approved_request_id": "REQ-410",
        "trip_id": "TRIP-410",
        "traveler_name": "Alex Rivera",
        "cost_center": "OPS-410",
        "expense_description": "Conference hotel folio",
        "expense_category": "lodging",
        "expense_amount": "640.00",
        "expense_date": "2025-10-09",
        "expense_vendor": "Pine Street Suites",
        "receipt_file_reference": "receipts/hotel-folio.pdf",
        "receipt_file_size_bytes": "2048",
        "receipt_total": "640.00",
        "receipt_date": "2025-10-09",
        "receipt_vendor": "Pine Street Suites",
        "receipt_ocr_text": "Pine Street Suites\nTotal: 640.00\n2025-10-09",
        "reimbursement_status": "manager_review",
        "manager_disposition": "Need lodging policy confirmation",
        "accounting_disposition": "Queue next export batch",
    }


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


def test_readyz_reports_oidc_provider_placeholder_overrides(monkeypatch) -> None:
    monkeypatch.setenv("TPP_BASE_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("TPP_OIDC_PROVIDER", "okta")
    monkeypatch.setenv("TPP_AUTH_MODE", "oidc")
    monkeypatch.setenv("TPP_OIDC_AUDIENCE", "trip-planner")
    monkeypatch.delenv("TPP_OIDC_ISSUER", raising=False)
    monkeypatch.delenv("TPP_OIDC_JWKS_URL", raising=False)

    client = TestClient(create_app())
    response = client.get("/readyz")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "misconfigured"
    assert payload["config"]["missing_config"] == [
        "TPP_OIDC_ISSUER",
        "TPP_OIDC_JWKS_URL",
    ]


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


def test_planner_route_audit_events_include_route_identifier(monkeypatch, tmp_path) -> None:
    _set_runtime_env(monkeypatch)
    store_path = tmp_path / "audit.sqlite3"
    monkeypatch.setenv(audit.AUDIT_PATH_ENV_VAR, str(store_path))
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
    audit.get_default_store().close()
    audit.reset_default_store()
    store = audit.SQLiteAuditEventStore(store_path)
    store.initialize()
    try:
        rows = list(store.query(event_type=audit.EVENT_AUTH_REQUEST))
    finally:
        store.close()
    assert [row.target_id for row in rows] == ["GET /api/planner/policy-snapshot"]


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


def test_oidc_token_allows_planner_routes(monkeypatch) -> None:
    _set_oidc_runtime_env(monkeypatch)
    client = TestClient(create_app())
    trip_plan = _load_fixture("proposal_submission.json")
    snapshot_request = _load_fixture("policy_snapshot_request.json")

    response = client.request(
        "GET",
        "/api/planner/policy-snapshot",
        headers=_oidc_auth_header(monkeypatch),
        json={"trip_plan": trip_plan, "request": snapshot_request},
    )

    assert response.status_code == 200


def test_oidc_token_fetches_jwks_over_http(monkeypatch) -> None:
    _set_oidc_runtime_env(monkeypatch)
    planner_auth._JWKS_CACHE.clear()
    token, jwks = _build_oidc_token_and_jwks()
    with _serve_jwks(jwks) as jwks_url:
        monkeypatch.setenv("TPP_OIDC_JWKS_URL", jwks_url)
        client = TestClient(create_app())
        trip_plan = _load_fixture("proposal_submission.json")
        snapshot_request = _load_fixture("policy_snapshot_request.json")

        response = client.request(
            "GET",
            "/api/planner/policy-snapshot",
            headers={"Authorization": f"Bearer {token}"},
            json={"trip_plan": trip_plan, "request": snapshot_request},
        )

    assert response.status_code == 200


def test_oidc_invalid_audience_returns_structured_bearer_error(monkeypatch) -> None:
    _set_oidc_runtime_env(monkeypatch)
    client = TestClient(create_app())
    trip_plan = _load_fixture("proposal_submission.json")
    snapshot_request = _load_fixture("policy_snapshot_request.json")

    response = client.request(
        "GET",
        "/api/planner/policy-snapshot",
        headers=_oidc_auth_header(monkeypatch, audience="wrong-audience"),
        json={"trip_plan": trip_plan, "request": snapshot_request},
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Bearer error="invalid_token"'
    assert response.json()["detail"]["error_code"] == "invalid_token"


def test_oidc_unsupported_algorithm_returns_structured_bearer_error(
    monkeypatch,
) -> None:
    _set_oidc_runtime_env(monkeypatch)
    planner_auth._JWKS_CACHE.clear()
    token = jwt.encode(
        {
            "iss": "https://accounts.google.com",
            "aud": "trip-planner",
            "sub": "planner@example.com",
            "exp": datetime.now(UTC) + timedelta(minutes=10),
            "nbf": datetime.now(UTC) - timedelta(seconds=5),
        },
        "shared-secret",
        algorithm="HS256",
        headers={"kid": "planner-key"},
    )
    monkeypatch.setattr(
        planner_auth,
        "_fetch_jwks_document",
        lambda _url: {"keys": [{"kid": "planner-key", "kty": "oct", "alg": "HS256"}]},
    )
    client = TestClient(create_app())
    trip_plan = _load_fixture("proposal_submission.json")
    snapshot_request = _load_fixture("policy_snapshot_request.json")

    response = client.request(
        "GET",
        "/api/planner/policy-snapshot",
        headers={"Authorization": f"Bearer {token}"},
        json={"trip_plan": trip_plan, "request": snapshot_request},
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Bearer error="invalid_token"'
    assert response.json()["detail"]["error_code"] == "invalid_token"


def test_oidc_jwks_fetch_failure_returns_structured_bearer_error(monkeypatch) -> None:
    _set_oidc_runtime_env(monkeypatch)
    planner_auth._JWKS_CACHE.clear()
    token, _jwks = _build_oidc_token_and_jwks()
    monkeypatch.setenv("TPP_OIDC_JWKS_URL", "http://127.0.0.1:1/jwks.json")
    client = TestClient(create_app())
    trip_plan = _load_fixture("proposal_submission.json")
    snapshot_request = _load_fixture("policy_snapshot_request.json")

    response = client.request(
        "GET",
        "/api/planner/policy-snapshot",
        headers={"Authorization": f"Bearer {token}"},
        json={"trip_plan": trip_plan, "request": snapshot_request},
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Bearer error="invalid_token"'
    assert response.json()["detail"]["error_code"] == "invalid_token"


def test_oidc_malformed_jwk_returns_structured_bearer_error(monkeypatch) -> None:
    _set_oidc_runtime_env(monkeypatch)
    planner_auth._JWKS_CACHE.clear()
    token, _jwks = _build_oidc_token_and_jwks()
    monkeypatch.setattr(
        planner_auth,
        "_fetch_jwks_document",
        lambda _url: {"keys": [{"kid": "planner-key", "kty": "RSA", "alg": "RS256"}]},
    )
    client = TestClient(create_app())
    trip_plan = _load_fixture("proposal_submission.json")
    snapshot_request = _load_fixture("policy_snapshot_request.json")

    response = client.request(
        "GET",
        "/api/planner/policy-snapshot",
        headers={"Authorization": f"Bearer {token}"},
        json={"trip_plan": trip_plan, "request": snapshot_request},
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Bearer error="invalid_token"'
    assert response.json()["detail"]["error_code"] == "invalid_token"


def test_readyz_reports_missing_oidc_audience(monkeypatch) -> None:
    _set_oidc_runtime_env(monkeypatch)
    monkeypatch.delenv("TPP_OIDC_AUDIENCE")

    client = TestClient(create_app())
    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["config"]["missing_config"] == ["TPP_OIDC_AUDIENCE"]


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


def test_main_fails_fast_when_runtime_is_misconfigured(monkeypatch, capsys) -> None:
    monkeypatch.delenv("TPP_BASE_URL", raising=False)
    monkeypatch.delenv("TPP_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("TPP_OIDC_PROVIDER", raising=False)
    monkeypatch.delenv("TPP_AUTH_MODE", raising=False)
    monkeypatch.delenv("TPP_BOOTSTRAP_SIGNING_SECRET", raising=False)

    exit_code = main([])
    assert exit_code == 1
    assert "missing:" in capsys.readouterr().err


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


def test_portal_home_and_request_form_render() -> None:
    client = TestClient(create_app())

    home = client.get("/portal")
    form = client.get("/portal/draft/new")

    assert home.status_code == 200
    assert "Travel Request Portal" in home.text
    assert form.status_code == 200
    assert 'data-template="draft-entry"' in form.text
    assert "Draft a travel request through the real service runtime." in form.text


def test_portal_request_form_get_stays_lightweight() -> None:
    client = TestClient(create_app())

    response = client.get("/portal/draft/new?traveler_name=Alex+Rivera")

    assert response.status_code == 200
    assert 'value="Alex Rivera"' not in response.text
    assert "Generated artifacts" not in response.text
    assert "Policy-lite posture" not in response.text


def test_expense_portal_form_renders() -> None:
    client = TestClient(create_app())

    response = client.get("/portal/expenses/new")

    assert response.status_code == 200
    assert "Prepare an expense report from an approved request." in response.text
    assert "Receipt intake" in response.text


def test_expense_portal_review_surfaces_missing_receipt_warning() -> None:
    store = PlannerProposalStore()
    client = TestClient(create_app(store))
    payload = _expense_form_payload()
    payload.pop("receipt_file_reference")
    payload.pop("receipt_file_size_bytes")
    payload.pop("receipt_total")
    payload.pop("receipt_date")
    payload.pop("receipt_vendor")
    payload.pop("receipt_ocr_text")

    response = client.post(
        "/portal/expenses/review",
        data=payload,
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert (
        "Receipt missing: reviewers should hold reimbursement until the traveler uploads support."
        in response.text
    )
    assert "Download CSV" in response.text
    assert store.expense_drafts_by_id


def test_expense_portal_generates_exports_and_policy_warning() -> None:
    store = PlannerProposalStore()
    client = TestClient(create_app(store))
    payload = _expense_form_payload()
    payload["expense_amount"] = "7500.00"
    payload["receipt_total"] = "7500.00"

    response = client.post(
        "/portal/expenses/review",
        data=payload,
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert (
        "Policy warning: manager or accounting review is required before reimbursement."
        in response.text
    )
    assert "Manual receipt entry overrides OCR values for total." in response.text

    match = re.search(r"/portal/expenses/([^/]+)/artifacts/expense-csv", response.text)
    assert match is not None
    draft_id = match.group(1)

    csv_export = client.get(f"/portal/expenses/{draft_id}/artifacts/expense-csv")
    excel_export = client.get(f"/portal/expenses/{draft_id}/artifacts/expense-xlsx")

    assert csv_export.status_code == 200
    assert b"date,vendor,amount,category,cost_center,receipt_link" in csv_export.content
    assert f"{draft_id}.csv" in csv_export.headers["content-disposition"]
    assert excel_export.status_code == 200
    assert excel_export.content.startswith(b"PK")
    assert f"{draft_id}.xlsx" in excel_export.headers["content-disposition"]


def test_expense_portal_invalid_amount_returns_validation_error() -> None:
    client = TestClient(create_app())
    payload = _expense_form_payload()
    payload["expense_amount"] = "not-a-decimal"

    response = client.post("/portal/expenses/review", data=payload)

    assert response.status_code == 400
    assert "One or more currency amounts are not valid decimal values." in response.text


def test_expense_portal_missing_approval_rules_returns_validation_error(
    monkeypatch,
) -> None:
    client = TestClient(create_app())
    payload = _expense_form_payload()

    monkeypatch.setattr("travel_plan_permission.approval._default_rules_path", lambda: None)
    monkeypatch.setattr("travel_plan_permission.approval._package_rules_resource", lambda: None)

    response = client.post("/portal/expenses/review", data=payload)

    assert response.status_code == 400
    assert (
        "Approval rules configuration is unavailable; expense policy review cannot be completed."
        in response.text
    )


def test_expense_portal_caches_artifacts_with_persisted_draft_id() -> None:
    store = PlannerProposalStore()
    client = TestClient(create_app(store))

    response = client.post(
        "/portal/expenses/review",
        data=_expense_form_payload(),
        follow_redirects=True,
    )

    assert response.status_code == 200
    match = re.search(r"/portal/expenses/([^/]+)/artifacts/expense-csv", response.text)
    assert match is not None
    draft_id = match.group(1)

    draft = store.lookup_expense_draft(draft_id)
    assert draft is not None
    assert draft_id in draft.cached_artifacts["expense-csv"].filename
    assert draft_id in draft.cached_artifacts["expense-xlsx"].filename
    assert "preview" not in draft.cached_artifacts["expense-csv"].filename.lower()
    assert "preview" not in draft.cached_artifacts["expense-xlsx"].filename.lower()
    assert b"EXP-PREVIEW" not in draft.cached_artifacts["expense-csv"].content


def test_expense_portal_rejects_invalid_decimal_input_without_saving() -> None:
    store = PlannerProposalStore()
    client = TestClient(create_app(store))
    payload = _expense_form_payload()
    payload["expense_amount"] = "not-a-decimal"

    response = client.post(
        "/portal/expenses/review",
        data=payload,
        follow_redirects=True,
    )

    assert response.status_code == 400
    assert "not-a-decimal" in response.text
    assert not store.expense_drafts_by_id


def test_portal_draft_validation_returns_bad_request_without_saving() -> None:
    store = PlannerProposalStore()
    client = TestClient(create_app(store))

    response = client.post(
        "/portal/draft",
        data={"traveler_name": "Alex Rivera", "business_purpose": "Partner summit"},
    )

    assert response.status_code == 400
    assert 'data-template="validation-feedback"' in response.text
    assert "Complete the missing details before this draft can be saved." in response.text
    assert store.portal_drafts_by_id == {}
    assert re.search(
        r'<ul class="missing-fields">.*?<li><code>destination_zip</code></li>',
        response.text,
        re.DOTALL,
    )
    assert "Where are you headed and what" in response.text


def test_portal_draft_validation_rejects_invalid_present_payload_without_saving() -> None:
    store = PlannerProposalStore()
    client = TestClient(create_app(store))
    payload = _portal_form_payload()
    payload["destination_zip"] = "98A01"

    response = client.post("/portal/draft", data=payload)

    assert response.status_code == 400
    assert 'data-template="validation-feedback"' in response.text
    assert store.portal_drafts_by_id == {}
    assert "destination_zip:" in response.text
    assert '<ul class="missing-fields">' not in response.text
    assert '<ul class="validation-errors">' in response.text


def test_portal_review_allows_optional_fields_to_remain_blank(monkeypatch) -> None:
    _set_runtime_env(monkeypatch)
    client = TestClient(create_app(PlannerProposalStore()))
    payload = _portal_form_payload()
    for field_name in (
        "cost_center",
        "event_registration_cost",
        "flight_pref_outbound.carrier_flight",
        "flight_pref_return.carrier_flight",
        "lowest_cost_roundtrip",
        "parking_estimate",
        "hotel.name",
        "hotel.address",
        "hotel.city_state",
        "hotel.nightly_rate",
        "hotel.nights",
        "hotel.conference_hotel",
        "hotel.price_compare_notes",
        "comparable_hotels[0].name",
        "comparable_hotels[0].nightly_rate",
        "ground_transport_pref",
        "notes",
    ):
        payload.pop(field_name)

    draft_id, _location = _create_portal_draft(client, payload=payload)
    response = _get_portal_review(client, draft_id)

    assert response.status_code == 200
    assert 'data-template="review-summary"' in response.text
    assert "Generated artifacts" in response.text
    assert "Missing required inputs" not in response.text


def test_portal_review_persists_policy_readiness_answers(monkeypatch) -> None:
    _set_runtime_env(monkeypatch)
    client = TestClient(create_app(PlannerProposalStore()))

    draft_id, _location = _create_portal_draft(client)
    response = _get_portal_review(client, draft_id)

    assert response.status_code == 200
    assert 'data-template="review-summary"' in response.text
    assert "<dt>booking_date</dt>" in response.text
    assert "<dd>2025-09-20</dd>" in response.text
    assert "<dt>cabin_class</dt>" in response.text
    assert "<dd>economy</dd>" in response.text
    assert "<dt>driving_cost</dt>" in response.text
    assert "<dd>120.00</dd>" in response.text


def test_portal_generates_review_artifacts_and_submission(monkeypatch) -> None:
    _set_runtime_env(monkeypatch)
    client = TestClient(create_app(PlannerProposalStore()))

    draft_id, _location = _create_portal_draft(client)
    response = _get_portal_review(client, draft_id)

    assert response.status_code == 200
    assert 'data-template="review-summary"' in response.text
    assert "Policy-lite posture" in response.text
    assert "Generated artifacts" in response.text
    assert "dev-token" not in response.text
    assert "planner-static-client" in response.text
    assert "via google" in response.text

    itinerary = client.get(
        f"/portal/review/{draft_id}/artifacts/itinerary",
        headers=AUTH_HEADER,
    )
    summary = client.get(
        f"/portal/review/{draft_id}/artifacts/summary",
        headers=AUTH_HEADER,
    )
    submit = client.post(
        f"/portal/review/{draft_id}/submit",
        headers=AUTH_HEADER,
        follow_redirects=True,
    )

    assert itinerary.status_code == 200
    assert itinerary.content.startswith(b"PK")
    assert summary.status_code == 200
    assert summary.content
    assert summary.headers["content-type"].startswith(("application/pdf", "text/plain"))
    assert submit.status_code == 200
    assert "Submission result" in submit.text


def test_portal_draft_submission_redirects_without_authorization_header(
    monkeypatch,
) -> None:
    _set_runtime_env(monkeypatch)
    client = TestClient(create_app(PlannerProposalStore()))

    response = client.post(
        "/portal/draft",
        data=_portal_form_payload(),
        follow_redirects=False,
    )

    assert response.status_code == 303
    location = response.headers["location"]
    assert "/portal/review/" in location


def test_submission_creates_manager_review_queue_entry(monkeypatch) -> None:
    _set_runtime_env(monkeypatch)
    store = PlannerProposalStore()
    client = TestClient(create_app(store))

    draft_id, _location = _create_portal_draft(client)

    submit = client.post(
        f"/portal/review/{draft_id}/submit",
        headers=AUTH_HEADER,
        follow_redirects=True,
    )

    assert submit.status_code == 200
    assert "Submission result" in submit.text
    review = store.lookup_manager_review_for_draft(draft_id)
    assert review is not None
    queue = client.get("/portal/manager/reviews", headers=AUTH_HEADER)
    detail = client.get(
        f"/portal/manager/reviews/{review.review_id}",
        headers=AUTH_HEADER,
    )

    assert queue.status_code == 200
    assert review.trip_plan.traveler_name in queue.text
    assert "pending_manager_review" in queue.text
    assert detail.status_code == 200
    assert "Current policy posture" in detail.text
    assert "Workflow event log" in detail.text


def test_manager_review_decision_updates_status_and_history(monkeypatch) -> None:
    _set_bootstrap_runtime_env(monkeypatch)
    store = PlannerProposalStore()
    client = TestClient(create_app(store))

    draft_id, _location = _create_portal_draft(client)
    traveler_header = _bootstrap_auth_header(
        subject="traveler",
        permissions=(Permission.CREATE,),
    )

    client.post(
        f"/portal/review/{draft_id}/submit",
        headers=traveler_header,
        follow_redirects=True,
    )
    review = store.lookup_manager_review_for_draft(draft_id)
    assert review is not None

    manager_header = _bootstrap_auth_header(
        subject="manager-reviewer",
        permissions=(Permission.VIEW, Permission.APPROVE),
    )

    decision = client.post(
        f"/portal/manager/reviews/{review.review_id}/decision",
        headers=manager_header,
        data={
            "actor_id": "manager-17",
            "action": "request_changes",
            "rationale": "Need a clearer justification before approval.",
        },
        follow_redirects=True,
    )

    assert decision.status_code == 200
    assert "changes_requested" in decision.text
    assert "Need a clearer justification before approval." in decision.text
    updated = store.lookup_manager_review(review.review_id)
    assert updated is not None
    assert updated.status.value == "changes_requested"
    assert updated.trip_plan.approval_history[-1].outcome.value == "flagged"
    assert updated.trip_plan.approval_history[-1].approver_id == "manager-17"


def test_manager_review_routes_require_authorization(monkeypatch) -> None:
    _set_runtime_env(monkeypatch)
    store = PlannerProposalStore()
    client = TestClient(create_app(store))

    draft_id, _location = _create_portal_draft(client)
    client.post(
        f"/portal/review/{draft_id}/submit",
        headers=AUTH_HEADER,
        follow_redirects=True,
    )
    review = store.lookup_manager_review_for_draft(draft_id)
    assert review is not None

    missing_queue = client.get("/portal/manager/reviews")
    missing_detail = client.get(f"/portal/manager/reviews/{review.review_id}")
    missing_decision = client.post(
        f"/portal/manager/reviews/{review.review_id}/decision",
        data={
            "actor_id": "manager-17",
            "action": "approve",
            "rationale": "Looks good.",
        },
    )

    assert missing_queue.status_code == 401
    assert missing_detail.status_code == 401
    assert missing_decision.status_code == 401


def test_manager_review_decision_requires_approve_permission(monkeypatch) -> None:
    _set_bootstrap_runtime_env(monkeypatch)
    store = PlannerProposalStore()
    client = TestClient(create_app(store))

    draft_id, _location = _create_portal_draft(client)
    client.post(
        f"/portal/review/{draft_id}/submit",
        headers=_bootstrap_auth_header(
            subject="traveler",
            permissions=(Permission.CREATE,),
        ),
        follow_redirects=True,
    )
    review = store.lookup_manager_review_for_draft(draft_id)
    assert review is not None

    decision = client.post(
        f"/portal/manager/reviews/{review.review_id}/decision",
        headers=_bootstrap_auth_header(
            subject="viewer-only",
            permissions=(Permission.VIEW,),
        ),
        data={
            "actor_id": "manager-17",
            "action": "approve",
            "rationale": "Looks good.",
        },
    )

    assert decision.status_code == 403
    assert "does not grant 'approve'" in decision.json()["detail"]


def test_manager_review_detail_hides_decision_form_for_read_only_role(
    monkeypatch,
) -> None:
    _set_runtime_env(monkeypatch)
    store = PlannerProposalStore()
    client = TestClient(create_app(store))

    draft_id, _location = _create_portal_draft(client)
    client.post(
        f"/portal/review/{draft_id}/submit",
        headers=AUTH_HEADER,
        follow_redirects=True,
    )
    review = store.lookup_manager_review_for_draft(draft_id)
    assert review is not None

    detail = client.get(
        f"/portal/manager/reviews/{review.review_id}?actor_role=traveler",
        headers=AUTH_HEADER,
    )

    assert detail.status_code == 200
    assert "Read-only role" in detail.text
    assert "Save manager decision" not in detail.text


def test_portal_admin_console_surfaces_permissions_runtime_and_audit_history(
    monkeypatch,
) -> None:
    _set_runtime_env(monkeypatch)
    store = PlannerProposalStore()
    client = TestClient(create_app(store))

    draft_id, _location = _create_portal_draft(client)
    client.post(
        f"/portal/review/{draft_id}/exceptions",
        data={
            "exception_type": "advance_booking",
            "amount": "6000",
            "justification": ("Need to lock in the only compliant conference fare. " * 2),
            "supporting_doc": "docs/approval-workflow.md",
        },
        follow_redirects=False,
    )
    client.post(
        f"/portal/review/{draft_id}/submit",
        headers=AUTH_HEADER,
        follow_redirects=True,
    )
    review = store.lookup_manager_review_for_draft(draft_id)
    assert review is not None
    client.get(
        f"/portal/review/{draft_id}/artifacts/summary",
        headers=AUTH_HEADER,
    )

    console = client.get(
        "/portal/admin?actor_role=finance_admin",
        headers=AUTH_HEADER,
    )

    assert console.status_code == 200
    assert "Portal admin console" in console.text
    assert "Role view simulation" in console.text
    assert "Authenticated token permissions" in console.text
    assert "finance_admin" in console.text
    assert "static-token" in console.text
    assert "advance_booking" in console.text
    assert "artifact_downloaded" in console.text


def test_manager_review_detail_uses_authenticated_permissions_for_actions(
    monkeypatch,
) -> None:
    _set_bootstrap_runtime_env(monkeypatch)
    store = PlannerProposalStore()
    client = TestClient(create_app(store))

    draft_id, _location = _create_portal_draft(client)
    client.post(
        f"/portal/review/{draft_id}/submit",
        headers=_bootstrap_auth_header(
            subject="traveler",
            permissions=(Permission.CREATE,),
        ),
        follow_redirects=True,
    )
    review = store.lookup_manager_review_for_draft(draft_id)
    assert review is not None

    detail = client.get(
        f"/portal/manager/reviews/{review.review_id}?actor_role=traveler",
        headers=_bootstrap_auth_header(
            subject="approver-8",
            permissions=(Permission.VIEW, Permission.APPROVE),
        ),
    )

    assert detail.status_code == 200
    assert "Role view simulation: <strong>traveler</strong>" in detail.text
    assert "Authenticated token permissions:" in detail.text
    assert "<code>approve</code>" in detail.text
    assert "Save manager decision" in detail.text


def test_exception_decision_updates_review_detail_and_audit_log(monkeypatch) -> None:
    _set_bootstrap_runtime_env(monkeypatch)
    store = PlannerProposalStore()
    client = TestClient(create_app(store))

    draft_id, _location = _create_portal_draft(client)
    client.post(
        f"/portal/review/{draft_id}/exceptions",
        data={
            "exception_type": "advance_booking",
            "amount": "6000",
            "justification": ("Need to lock in the only compliant conference fare. " * 2),
            "supporting_doc": "docs/approval-workflow.md",
        },
        follow_redirects=False,
    )
    client.post(
        f"/portal/review/{draft_id}/submit",
        headers=_bootstrap_auth_header(
            subject="traveler",
            permissions=(Permission.CREATE,),
        ),
        follow_redirects=True,
    )
    review = store.lookup_manager_review_for_draft(draft_id)
    assert review is not None

    decision = client.post(
        f"/portal/admin/exceptions/{draft_id}/0/decision?actor_role=approver",
        headers=_bootstrap_auth_header(
            subject="approver-7",
            permissions=(Permission.VIEW, Permission.APPROVE),
        ),
        data={
            "actor_id": "approver-7",
            "decision": "approve",
            "notes": "Conference booking window requires the exception.",
        },
        follow_redirects=True,
    )

    assert decision.status_code == 200
    assert "approved by approver-7" in decision.text
    assert "exception · approved by approver-7" in decision.text


def test_exception_rejection_keeps_notes_in_audit_log(monkeypatch) -> None:
    _set_bootstrap_runtime_env(monkeypatch)
    store = PlannerProposalStore()
    client = TestClient(create_app(store))

    draft_id, _location = _create_portal_draft(client)
    client.post(
        f"/portal/review/{draft_id}/exceptions",
        data={
            "exception_type": "advance_booking",
            "amount": "6000",
            "justification": ("Need to lock in the only compliant conference fare. " * 2),
            "supporting_doc": "docs/approval-workflow.md",
        },
        follow_redirects=False,
    )

    decision = client.post(
        f"/portal/admin/exceptions/{draft_id}/0/decision?actor_role=approver",
        headers=_bootstrap_auth_header(
            subject="approver-9",
            permissions=(Permission.VIEW, Permission.APPROVE),
        ),
        data={
            "actor_id": "approver-9",
            "decision": "reject",
            "notes": "Missing conference justification and fare documentation.",
        },
        follow_redirects=False,
    )

    assert decision.status_code == 303
    assert any(
        event.outcome == "rejected"
        and event.metadata
        and event.metadata.get("notes")
        == "Missing conference justification and fare documentation."
        for event in store.list_audit_events()
    )


def test_portal_submit_exception_request_returns_400_for_invalid_payload(
    monkeypatch,
) -> None:
    _set_runtime_env(monkeypatch)
    client = TestClient(create_app(PlannerProposalStore()), raise_server_exceptions=False)

    draft_id, _location = _create_portal_draft(client)

    response = client.post(
        f"/portal/review/{draft_id}/exceptions",
        data={
            "exception_type": "advance_booking",
            "amount": "-5",
            "justification": "too short",
        },
        follow_redirects=True,
    )

    assert response.status_code == 400
    assert "Exception request error" in response.text
    assert "greater than or equal to 0" in response.text


def test_portal_exception_decision_returns_404_for_missing_request(monkeypatch) -> None:
    _set_bootstrap_runtime_env(monkeypatch)
    client = TestClient(create_app(PlannerProposalStore()))

    response = client.post(
        "/portal/admin/exceptions/missing-draft/0/decision?actor_role=approver",
        headers={
            "Authorization": "Bearer "
            + mint_bootstrap_token(
                subject="approver-7",
                permissions=(Permission.VIEW, Permission.APPROVE),
                provider="google",
                secret="bootstrap-secret-123",
                expires_in_seconds=600,
            )
        },
        data={
            "actor_id": "approver-7",
            "decision": "approve",
            "notes": "No matching request.",
        },
        follow_redirects=False,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Exception request not found."


def test_save_portal_draft_evicts_exception_state_with_oldest_draft() -> None:
    store = PlannerProposalStore()
    old_draft = store.save_portal_draft({"traveler_name": "First"})
    store.create_exception_request(
        old_draft.draft_id,
        http_service.ExceptionRequest(
            type=http_service.ExceptionType.ADVANCE_BOOKING,
            justification="Need to keep the first bounded exception state attached. " * 2,
            requestor="traveler-1",
            amount="100",
        ),
    )

    for index in range(1, http_service._PORTAL_MAX_DRAFTS + 1):
        store.save_portal_draft({"traveler_name": f"Traveler {index}"})

    assert old_draft.draft_id not in store.portal_drafts_by_id
    assert old_draft.draft_id not in store.exception_requests_by_draft_id


def test_manager_review_store_returns_copies() -> None:
    store = PlannerProposalStore()
    fixture = _load_fixture("proposal_submission.json")
    trip_plan = http_service.TripPlan.model_validate(fixture)
    snapshot = http_service.get_policy_snapshot(trip_plan)
    result = http_service.check_trip_plan(trip_plan)

    created = store.manager_reviews.create_or_get(
        draft_id="draft-123",
        trip_plan=trip_plan,
        policy_snapshot=snapshot,
        policy_result=result,
    )
    created.trip_plan.traveler_name = "Mutated"

    listed = store.manager_reviews.list_reviews()
    listed[0].trip_plan.traveler_name = "Mutated Again"

    lookup = store.lookup_manager_review(created.review_id)
    assert lookup is not None
    assert lookup.trip_plan.traveler_name == fixture["traveler_name"]


def test_portal_artifact_downloads_use_cached_review_artifacts(monkeypatch) -> None:
    _set_runtime_env(monkeypatch)
    client = TestClient(create_app(PlannerProposalStore()))

    draft_id, _location = _create_portal_draft(client)
    response = _get_portal_review(client, draft_id)
    assert response.status_code == 200

    def fail_render(*_args, **_kwargs):
        raise AssertionError("artifact download should use cached payloads")

    monkeypatch.setattr(portal_review, "render_travel_spreadsheet_bytes", fail_render)
    monkeypatch.setattr(portal_review, "build_output_bundle", fail_render)

    itinerary = client.get(
        f"/portal/review/{draft_id}/artifacts/itinerary",
        headers=AUTH_HEADER,
    )
    summary = client.get(
        f"/portal/review/{draft_id}/artifacts/summary",
        headers=AUTH_HEADER,
    )

    assert itinerary.status_code == 200
    assert itinerary.content.startswith(b"PK")
    assert summary.status_code == 200
    assert summary.content


def test_portal_submit_requires_bearer_token(monkeypatch) -> None:
    _set_runtime_env(monkeypatch)
    client = TestClient(create_app(PlannerProposalStore()))

    draft_id, _location = _create_portal_draft(client)

    submit = client.post(
        f"/portal/review/{draft_id}/submit",
        follow_redirects=True,
    )

    assert submit.status_code == 401
    assert submit.json()["detail"] == "Missing bearer token."


def test_portal_review_surface_requires_bearer_token(monkeypatch) -> None:
    _set_bootstrap_runtime_env(monkeypatch)
    client = TestClient(create_app(PlannerProposalStore()))

    draft_id, _location = _create_portal_draft(client)
    review = client.get(f"/portal/review/{draft_id}")

    assert review.status_code == 401
    assert review.json()["detail"] == "Missing bearer token."


def test_portal_review_state_survives_restart(monkeypatch, tmp_path) -> None:
    _set_runtime_env(monkeypatch)
    state_path = tmp_path / "portal-runtime-state.sqlite3"

    first_client = TestClient(create_app(PlannerProposalStore(state_path=state_path)))
    draft_id, _location = _create_portal_draft(first_client)
    response = _get_portal_review(first_client, draft_id)

    assert response.status_code == 200
    assert state_path.exists()

    second_client = TestClient(create_app(PlannerProposalStore(state_path=state_path)))
    restored = second_client.get(f"/portal/review/{draft_id}", headers=AUTH_HEADER)

    assert restored.status_code == 200
    assert 'data-template="review-summary"' in restored.text
    assert f"Draft {draft_id}" in restored.text
    assert "Generated artifacts" in restored.text


def test_expense_review_state_survives_restart(tmp_path) -> None:
    state_path = tmp_path / "portal-runtime-state.sqlite3"

    first_client = TestClient(create_app(PlannerProposalStore(state_path=state_path)))
    review = first_client.post(
        "/portal/expenses/review",
        data=_expense_form_payload(),
        follow_redirects=True,
    )

    assert review.status_code == 200
    match = re.search(r"/portal/expenses/([^/]+)/artifacts/expense-csv", review.text)
    assert match is not None
    draft_id = match.group(1)

    second_client = TestClient(create_app(PlannerProposalStore(state_path=state_path)))
    restored = second_client.get(f"/portal/expenses/{draft_id}")
    csv_export = second_client.get(f"/portal/expenses/{draft_id}/artifacts/expense-csv")
    excel_export = second_client.get(f"/portal/expenses/{draft_id}/artifacts/expense-xlsx")

    assert restored.status_code == 200
    assert f"Expense draft {draft_id}" in restored.text
    assert "Download CSV" in restored.text
    assert csv_export.status_code == 200
    assert f"{draft_id}.csv" in csv_export.headers["content-disposition"]
    assert b"date,vendor,amount,category,cost_center,receipt_link" in csv_export.content
    assert excel_export.status_code == 200
    assert f"{draft_id}.xlsx" in excel_export.headers["content-disposition"]
    assert excel_export.content.startswith(b"PK")


def test_expense_drafts_round_trip_serialize_and_load(tmp_path) -> None:
    state_path = tmp_path / "portal-runtime-state.sqlite3"
    first_store = PlannerProposalStore(state_path=state_path)
    draft = first_store.save_expense_draft(_expense_form_payload())
    first_store.cache_expense_artifacts(
        draft.draft_id,
        {
            "expense-csv": PortalArtifact(
                filename=f"{draft.draft_id}.csv",
                content=b"date,vendor,amount\n2026-01-15,Riverfront Hotel,249.00\n",
                media_type="text/csv",
            )
        },
    )

    restored_store = PlannerProposalStore(state_path=state_path)
    assert (
        restored_store._serialize_state()["expense_drafts_by_id"]
        == first_store._serialize_state()["expense_drafts_by_id"]
    )


def test_in_process_audit_log_survives_restart(tmp_path) -> None:
    state_path = tmp_path / "portal-runtime-state.sqlite3"
    first_store = PlannerProposalStore(state_path=state_path)
    first_store.security.audit_log.record(
        event_type=AuditEventType.AUTHENTICATION,
        actor="static-token",
        subject="planner-admin",
        outcome="success",
        metadata={"provider": "static-token"},
    )
    first_store.security.audit_log.record(
        event_type=AuditEventType.REVIEW,
        actor="workflow-portal",
        subject="review-123",
        outcome="proposal_status_change",
        metadata={
            "proposal_id": "prop-123",
            "from_status": "submitted",
            "to_status": "approved",
        },
    )
    first_store.save_expense_draft(_expense_form_payload())

    restored_store = PlannerProposalStore(state_path=state_path)
    restored_events = restored_store.list_audit_events()
    assert len(restored_events) >= 2
    assert {
        (event.event_type, event.outcome) for event in restored_events
    }.issuperset(
        {
        (AuditEventType.AUTHENTICATION, "success"),
        (AuditEventType.REVIEW, "proposal_status_change"),
        }
    )

    assert any(
        event.event_type == AuditEventType.AUTHENTICATION
        and event.actor == "static-token"
        and event.subject == "planner-admin"
        and event.outcome == "success"
        and event.metadata == {"provider": "static-token"}
        for event in restored_events
    )
    assert any(
        event.event_type == AuditEventType.REVIEW
        and event.actor == "workflow-portal"
        and event.subject == "review-123"
        and event.outcome == "proposal_status_change"
        and event.metadata
        == {
            "proposal_id": "prop-123",
            "from_status": "submitted",
            "to_status": "approved",
        }
        for event in restored_events
    )


def test_audit_events_round_trip_serialize_and_load(tmp_path) -> None:
    state_path = tmp_path / "portal-runtime-state.sqlite3"
    first_store = PlannerProposalStore(state_path=state_path)
    first_store.security.audit_log.record(
        event_type=AuditEventType.AUTHENTICATION,
        actor="static-token",
        subject="planner-admin",
        outcome="success",
        metadata={"provider": "static-token"},
    )
    first_store.security.audit_log.record(
        event_type=AuditEventType.REVIEW,
        actor="workflow-portal",
        subject="review-123",
        outcome="proposal_status_change",
        metadata={
            "proposal_id": "prop-123",
            "from_status": "submitted",
            "to_status": "approved",
        },
    )
    first_store.store.save_snapshot(first_store._serialize_state())

    restored_store = PlannerProposalStore(state_path=state_path)
    assert (
        restored_store._serialize_state()["audit_events"]
        == first_store._serialize_state()["audit_events"]
    )


def test_portal_submission_result_survives_restart(monkeypatch, tmp_path) -> None:
    _set_runtime_env(monkeypatch)
    state_path = tmp_path / "portal-runtime-state.sqlite3"

    first_client = TestClient(create_app(PlannerProposalStore(state_path=state_path)))
    draft_id, _location = _create_portal_draft(first_client)
    submit = first_client.post(
        f"/portal/review/{draft_id}/submit",
        headers=AUTH_HEADER,
        follow_redirects=True,
    )

    assert submit.status_code == 200
    assert "Submission result" in submit.text

    second_client = TestClient(create_app(PlannerProposalStore(state_path=state_path)))
    restored = second_client.get(f"/portal/review/{draft_id}", headers=AUTH_HEADER)

    assert restored.status_code == 200
    assert "Submission result" in restored.text
    assert "Open manager review" in restored.text


def test_submission_status_lookup_survives_restart(monkeypatch, tmp_path) -> None:
    _set_runtime_env(monkeypatch, provider="okta")
    state_path = tmp_path / "portal-runtime-state.sqlite3"
    first_client = TestClient(create_app(PlannerProposalStore(state_path=state_path)))
    trip_plan = _load_fixture("proposal_submission.json")
    request_payload = {
        "trip_id": trip_plan["trip_id"],
        "proposal_id": "proposal-123",
        "proposal_version": "proposal-v1",
        "payload": {"selected_options": ["flight-1", "hotel-3"]},
    }

    submit_response = first_client.post(
        "/api/planner/proposals",
        headers=AUTH_HEADER,
        json={"trip_plan": trip_plan, "request": request_payload},
    )

    assert submit_response.status_code == 200
    execution_id = str(submit_response.json()["result_payload"]["execution_id"])

    second_client = TestClient(create_app(PlannerProposalStore(state_path=state_path)))
    status_response = second_client.get(
        f"/api/planner/proposals/proposal-123/executions/{execution_id}",
        headers=AUTH_HEADER,
    )
    evaluation_response = second_client.get(
        f"/api/planner/executions/{execution_id}/evaluation-result",
        headers=AUTH_HEADER,
    )

    assert status_response.status_code == 200
    assert evaluation_response.status_code == 200


def test_portal_artifact_download_requires_view_permission(monkeypatch) -> None:
    _set_bootstrap_runtime_env(monkeypatch)
    client = TestClient(create_app(PlannerProposalStore()))

    draft_id, _location = _create_portal_draft(client)
    artifact = client.get(f"/portal/review/{draft_id}/artifacts/itinerary")
    create_only_token = mint_bootstrap_token(
        subject="portal-submit-only",
        permissions=(Permission.CREATE,),
        provider="google",
        secret="bootstrap-secret-123",
        expires_in_seconds=600,
    )
    forbidden = client.get(
        f"/portal/review/{draft_id}/artifacts/itinerary",
        headers={"Authorization": f"Bearer {create_only_token}"},
    )

    assert artifact.status_code == 401
    assert artifact.json()["detail"] == "Missing bearer token."
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"] == "Bootstrap token does not grant 'view'."


def test_portal_review_shows_auth_posture_and_hides_submit_for_view_only(
    monkeypatch,
) -> None:
    _set_bootstrap_runtime_env(monkeypatch)
    client = TestClient(create_app(PlannerProposalStore()))

    draft_id, _location = _create_portal_draft(client)
    view_only = _get_portal_review(
        client,
        draft_id,
        headers=_bootstrap_auth_header(
            subject="planner-reviewer",
            permissions=(Permission.VIEW,),
        ),
    )
    creator = _get_portal_review(
        client,
        draft_id,
        headers=_bootstrap_auth_header(
            subject="planner-author",
            permissions=(Permission.VIEW, Permission.CREATE),
        ),
    )

    assert view_only.status_code == 200
    assert "planner-reviewer" in view_only.text
    assert "via google" in view_only.text
    assert "Permission posture:" in view_only.text
    assert "Submit request" not in view_only.text
    assert "Submission stays hidden until the caller has `create` permission." in view_only.text
    assert creator.status_code == 200
    assert "planner-author" in creator.text
    assert "Submit request" in creator.text


def test_portal_review_detail_and_artifacts_require_view_permission(
    monkeypatch,
) -> None:
    _set_bootstrap_runtime_env(monkeypatch)
    client = TestClient(create_app(PlannerProposalStore()))
    draft_id, _location = _create_portal_draft(client)

    missing_detail = client.get(f"/portal/review/{draft_id}")
    missing_artifact = client.get(f"/portal/review/{draft_id}/artifacts/summary")
    create_only_header = _bootstrap_auth_header(
        subject="submit-only",
        permissions=(Permission.CREATE,),
    )
    forbidden_detail = client.get(
        f"/portal/review/{draft_id}",
        headers=create_only_header,
    )
    forbidden_artifact = client.get(
        f"/portal/review/{draft_id}/artifacts/summary",
        headers=create_only_header,
    )

    assert missing_detail.status_code == 401
    assert missing_artifact.status_code == 401
    assert forbidden_detail.status_code == 403
    assert forbidden_artifact.status_code == 403


def test_portal_routes_do_not_leave_legacy_request_paths_active() -> None:
    app = create_app()
    paths = {route.path for route in app.routes}

    assert "/portal/draft/new" in paths
    assert "/portal/draft" in paths
    assert "/portal/review/{draft_id}" in paths
    assert "/portal/expenses/new" in paths
    assert "/portal/expenses/review" in paths
    assert "/portal/expenses/{draft_id}" in paths
    assert all(not path.startswith("/portal/requests") for path in paths)


def test_portal_artifacts_raise_runtime_error_without_bundle_mappings(
    monkeypatch,
) -> None:
    _set_runtime_env(monkeypatch)
    client = TestClient(create_app(PlannerProposalStore()), raise_server_exceptions=False)

    def invalid_bundle(**_kwargs):
        return {"itinerary_excel": "bad", "summary_pdf": "bad"}

    monkeypatch.setattr(portal_review, "build_output_bundle", invalid_bundle)

    draft_id, _location = _create_portal_draft(client)
    response = client.get(
        f"/portal/review/{draft_id}",
        headers=AUTH_HEADER,
    )

    assert response.status_code == 500


def test_portal_artifacts_runtime_error_survives_python_optimized_mode() -> None:
    project_root = Path(__file__).resolve().parents[2]
    script = """
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "src"))

import travel_plan_permission.portal_review as portal_review

portal_review.render_travel_spreadsheet_bytes = lambda *args, **kwargs: b"x"
portal_review.build_output_bundle = (
    lambda **kwargs: {"itinerary_excel": "bad", "summary_pdf": "bad"}
)

try:
    portal_review._portal_artifacts(canonical=object(), plan=object(), answers={})
except RuntimeError:
    raise SystemExit(0)
except Exception as exc:
    print(type(exc).__name__, exc)
    raise SystemExit(2)

raise SystemExit(1)
"""

    result = subprocess.run(
        [sys.executable, "-O", "-c", script],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
