from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from travel_plan_permission import http_service
from travel_plan_permission.http_service import PlannerProposalStore, create_app, main
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


def test_portal_draft_validation_returns_bad_request_without_saving() -> None:
    store = PlannerProposalStore()
    client = TestClient(create_app(store))

    response = client.post(
        "/portal/draft",
        data={"traveler_name": "Alex Rivera", "business_purpose": "Partner summit"},
    )

    assert response.status_code == 400
    assert 'data-template="validation-feedback"' in response.text
    assert (
        "Complete the missing details before this draft can be saved." in response.text
    )
    assert store.portal_drafts_by_id == {}
    assert re.search(
        r'<ul class="missing-fields">.*?<li><code>destination_zip</code></li>',
        response.text,
        re.DOTALL,
    )
    assert "Where are you headed and what" in response.text


def test_portal_draft_validation_rejects_invalid_present_payload_without_saving() -> (
    None
):
    store = PlannerProposalStore()
    client = TestClient(create_app(store))
    payload = _portal_form_payload()
    payload["destination_zip"] = "98A01"

    response = client.post("/portal/draft", data=payload)

    assert response.status_code == 400
    assert 'data-template="validation-feedback"' in response.text
    assert store.portal_drafts_by_id == {}
    assert "destination_zip:" in response.text


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

    response = client.post(
        "/portal/draft",
        data=payload,
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert 'data-template="review-summary"' in response.text
    assert "Generated artifacts" in response.text
    assert "Missing required inputs" not in response.text


def test_portal_review_persists_policy_readiness_answers(monkeypatch) -> None:
    _set_runtime_env(monkeypatch)
    client = TestClient(create_app(PlannerProposalStore()))

    response = client.post(
        "/portal/draft",
        data=_portal_form_payload(),
        follow_redirects=True,
    )

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

    response = client.post(
        "/portal/draft",
        data=_portal_form_payload(),
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert 'data-template="review-summary"' in response.text
    assert "Policy-lite posture" in response.text
    assert "Generated artifacts" in response.text

    match = re.search(r"/portal/review/([^/]+)/artifacts/itinerary", response.text)
    assert match is not None
    draft_id = match.group(1)

    itinerary = client.get(f"/portal/review/{draft_id}/artifacts/itinerary")
    summary = client.get(f"/portal/review/{draft_id}/artifacts/summary")
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

    response = client.post(
        "/portal/draft",
        data=_portal_form_payload(),
        follow_redirects=True,
    )
    draft_match = re.search(
        r"/portal/review/([^/]+)/artifacts/itinerary", response.text
    )
    assert draft_match is not None
    draft_id = draft_match.group(1)

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

    response = client.post(
        "/portal/draft",
        data=_portal_form_payload(),
        follow_redirects=True,
    )
    draft_match = re.search(
        r"/portal/review/([^/]+)/artifacts/itinerary", response.text
    )
    assert draft_match is not None
    draft_id = draft_match.group(1)

    traveler_token = mint_bootstrap_token(
        subject="traveler",
        permissions=(Permission.CREATE,),
        provider="google",
        secret="bootstrap-secret-123",
        expires_in_seconds=600,
    )

    client.post(
        f"/portal/review/{draft_id}/submit",
        headers={"Authorization": f"Bearer {traveler_token}"},
        follow_redirects=True,
    )
    review = store.lookup_manager_review_for_draft(draft_id)
    assert review is not None

    manager_token = mint_bootstrap_token(
        subject="manager-reviewer",
        permissions=(Permission.VIEW, Permission.APPROVE),
        provider="google",
        secret="bootstrap-secret-123",
        expires_in_seconds=600,
    )

    decision = client.post(
        f"/portal/manager/reviews/{review.review_id}/decision",
        headers={"Authorization": f"Bearer {manager_token}"},
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

    response = client.post(
        "/portal/draft",
        data=_portal_form_payload(),
        follow_redirects=True,
    )
    draft_match = re.search(
        r"/portal/review/([^/]+)/artifacts/itinerary", response.text
    )
    assert draft_match is not None
    draft_id = draft_match.group(1)
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

    response = client.post(
        "/portal/draft",
        data=_portal_form_payload(),
        follow_redirects=True,
    )
    draft_match = re.search(
        r"/portal/review/([^/]+)/artifacts/itinerary", response.text
    )
    assert draft_match is not None
    draft_id = draft_match.group(1)
    client.post(
        f"/portal/review/{draft_id}/submit",
        headers={
            "Authorization": "Bearer "
            + mint_bootstrap_token(
                subject="traveler",
                permissions=(Permission.CREATE,),
                provider="google",
                secret="bootstrap-secret-123",
                expires_in_seconds=600,
            )
        },
        follow_redirects=True,
    )
    review = store.lookup_manager_review_for_draft(draft_id)
    assert review is not None

    viewer_token = mint_bootstrap_token(
        subject="viewer-only",
        permissions=(Permission.VIEW,),
        provider="google",
        secret="bootstrap-secret-123",
        expires_in_seconds=600,
    )
    decision = client.post(
        f"/portal/manager/reviews/{review.review_id}/decision",
        headers={"Authorization": f"Bearer {viewer_token}"},
        data={
            "actor_id": "manager-17",
            "action": "approve",
            "rationale": "Looks good.",
        },
    )

    assert decision.status_code == 403
    assert "does not grant 'approve'" in decision.json()["detail"]


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

    response = client.post(
        "/portal/draft",
        data=_portal_form_payload(),
        follow_redirects=True,
    )

    assert response.status_code == 200
    match = re.search(r"/portal/review/([^/]+)/artifacts/itinerary", response.text)
    assert match is not None
    draft_id = match.group(1)

    def fail_render(*_args, **_kwargs):
        raise AssertionError("artifact download should use cached payloads")

    monkeypatch.setattr(http_service, "render_travel_spreadsheet_bytes", fail_render)
    monkeypatch.setattr(http_service, "build_output_bundle", fail_render)

    itinerary = client.get(f"/portal/review/{draft_id}/artifacts/itinerary")
    summary = client.get(f"/portal/review/{draft_id}/artifacts/summary")

    assert itinerary.status_code == 200
    assert itinerary.content.startswith(b"PK")
    assert summary.status_code == 200
    assert summary.content


def test_portal_submit_requires_bearer_token(monkeypatch) -> None:
    _set_runtime_env(monkeypatch)
    client = TestClient(create_app(PlannerProposalStore()))

    response = client.post(
        "/portal/draft",
        data=_portal_form_payload(),
        follow_redirects=True,
    )
    match = re.search(r"/portal/review/([^/]+)/artifacts/itinerary", response.text)
    assert match is not None
    draft_id = match.group(1)

    submit = client.post(
        f"/portal/review/{draft_id}/submit",
        follow_redirects=True,
    )

    assert submit.status_code == 401
    assert submit.json()["detail"] == "Missing bearer token."


def test_portal_routes_do_not_leave_legacy_request_paths_active() -> None:
    app = create_app()
    paths = {route.path for route in app.routes}

    assert "/portal/draft/new" in paths
    assert "/portal/draft" in paths
    assert "/portal/review/{draft_id}" in paths
    assert all(not path.startswith("/portal/requests") for path in paths)


def test_portal_artifacts_raise_runtime_error_without_bundle_mappings(
    monkeypatch,
) -> None:
    _set_runtime_env(monkeypatch)
    client = TestClient(
        create_app(PlannerProposalStore()), raise_server_exceptions=False
    )

    def invalid_bundle(**_kwargs):
        return {"itinerary_excel": "bad", "summary_pdf": "bad"}

    monkeypatch.setattr(http_service, "build_output_bundle", invalid_bundle)

    response = client.post(
        "/portal/draft",
        data=_portal_form_payload(),
    )

    assert response.status_code == 500
