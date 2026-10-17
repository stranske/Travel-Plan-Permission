"""Real ASGI/auth/persistence contract for owner-scoped portal receipts."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from travel_plan_permission.http_service import PlannerProposalStore, create_app
from travel_plan_permission.planner_auth import mint_bootstrap_token
from travel_plan_permission.planner_client import (
    PlannerHttpError,
    PlannerJsonResponse,
    TravelPlanPermissionClient,
)
from travel_plan_permission.security import Permission

from .test_http_service import _portal_form_payload, _set_bootstrap_runtime_env

BASE = "/api/planner/portal-handoffs"


def auth(
    subject="traveler-a",
    permissions=(Permission.VIEW, Permission.CREATE),
    provider="google",
):
    token = mint_bootstrap_token(
        subject=subject,
        permissions=permissions,
        provider=provider,
        secret="bootstrap-secret-123",
        expires_in_seconds=600,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def app_client(monkeypatch, tmp_path):
    _set_bootstrap_runtime_env(monkeypatch)
    store = PlannerProposalStore(state_path=tmp_path / "receipts.sqlite3")
    return TestClient(create_app(store)), store


def payload(**updates):
    return {
        "handoff_id": "handoff-123",
        "snapshot_version": "trip-v7",
        "answers": _portal_form_payload(),
        **updates,
    }


def prepare(client, **updates):
    result = client.post(BASE, json=payload(**updates), headers=auth())
    assert result.status_code == 200, result.text
    return result.json()


def lookup(client, headers=None, version="trip-v7", handoff="handoff-123"):
    return client.get(
        f"{BASE}/{handoff}",
        params={"snapshot_version": version},
        headers=headers or auth(),
    )


def test_real_submission_manager_decision_and_restart(app_client, tmp_path):
    client, store = app_client
    prepared = prepare(client)
    assert prepared["state"] == "prepared"
    assert all(
        prepared[k] is None
        for k in ("request_id", "execution_id", "review_id", "decision", "submitted_at")
    )
    assert store.list_manager_reviews() == []
    draft_id = prepared["draft_id"]
    submitted = client.post(f"/portal/review/{draft_id}/submit", headers=auth())
    assert submitted.status_code == 200, submitted.text
    pending = lookup(client).json()
    assert pending["state"] == "pending_review", "submission must use the persisted manager queue"
    assert pending["request_id"] and pending["execution_id"] and pending["submitted_at"]
    review_id = pending["review_id"]
    assert store.lookup_manager_review(review_id).draft_id == draft_id
    decision = client.post(
        f"/portal/manager/reviews/{review_id}/decision",
        headers=auth("manager", (Permission.APPROVE,)),
        data={"action": "approve", "rationale": "Authorized real-app approval"},
        follow_redirects=False,
    )
    assert decision.status_code == 303, decision.text
    recorded = lookup(client).json()
    assert recorded["state"] == "decision_recorded" and recorded["decision"] == "approved"
    assert recorded["decision_at"]
    store.close()
    reloaded = PlannerProposalStore(state_path=tmp_path / "receipts.sqlite3")
    restarted = lookup(TestClient(create_app(reloaded))).json()
    assert {k: v for k, v in restarted.items() if k != "observed_at"} == {
        k: v for k, v in recorded.items() if k != "observed_at"
    }


@pytest.mark.parametrize("decision", ["reject", "request_changes"])
def test_decision_is_not_reset_by_submission_retry(app_client, decision):
    client, store = app_client
    draft = prepare(client)
    url = f"/portal/review/{draft['draft_id']}/submit"
    assert client.post(url, headers=auth()).status_code == 200
    pending = lookup(client).json()
    response = client.post(
        f"/portal/manager/reviews/{pending['review_id']}/decision",
        headers=auth("manager", (Permission.APPROVE,)),
        data={"action": decision, "rationale": "Recorded decision"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    before = lookup(client).json()
    assert client.post(url, headers=auth()).status_code == 200
    after = lookup(client).json()
    assert after["decision"] == before["decision"], "retry must preserve the recorded decision"
    assert after["decision_at"] == before["decision_at"]
    assert len(store.list_manager_reviews()) == 1


def test_owner_is_identity_not_traveler_name_or_id(app_client):
    client, _ = app_client
    prepared = prepare(client)
    foreign = auth("traveler-b")
    response = lookup(client, headers=foreign)
    assert response.status_code == 404, "foreign subject must not read the receipt"
    assert response.json() == lookup(client, headers=foreign, handoff="absent").json()
    assert prepared["draft_id"] not in response.text
    for url in [
        f"/portal/review/{prepared['draft_id']}",
        f"/portal/review/{prepared['draft_id']}/submit",
        f"/portal/review/{prepared['draft_id']}/exceptions",
    ]:
        result = (
            client.get(url, headers=foreign)
            if url.endswith(prepared["draft_id"])
            else client.post(url, headers=foreign)
        )
        assert result.status_code == 404, url
    # Even an approver cannot use this traveler-scoped API to inspect arbitrary receipts.
    assert (
        lookup(client, headers=auth("manager", (Permission.VIEW, Permission.APPROVE))).status_code
        == 404
    )
    own = client.post(BASE, json=payload(), headers=foreign).json()
    assert own["draft_id"] != prepared["draft_id"]


@pytest.mark.parametrize("headers,status", [({}, 401), ({"Authorization": "Bearer tampered"}, 503)])
def test_actual_auth_rejects_absent_and_invalid_credentials(app_client, headers, status):
    client, _ = app_client
    assert client.post(BASE, json=payload(), headers=headers).status_code == status
    assert (
        client.get(f"{BASE}/handoff-123?snapshot_version=trip-v7", headers=headers).status_code
        == status
    )


def test_permissions_and_wrong_provider_are_checked_by_real_auth(app_client):
    client, _ = app_client
    assert (
        client.post(BASE, json=payload(), headers=auth(permissions=(Permission.VIEW,))).status_code
        == 403
    )
    prepare(client)
    assert lookup(client, headers=auth(permissions=(Permission.CREATE,))).status_code == 403
    assert lookup(client, headers=auth(provider="okta")).status_code == 403
    assert (
        client.post(
            "/portal/manager/reviews/arbitrary/decision",
            headers=auth(),
            data={"action": "approve"},
        ).status_code
        == 403
    )


def test_static_shared_token_cannot_define_traveler_ownership(app_client, monkeypatch):
    client, _ = app_client
    monkeypatch.setenv("TPP_AUTH_MODE", "static-token")
    monkeypatch.setenv("TPP_ACCESS_TOKEN", "static-client-token")
    assert (
        client.post(
            BASE,
            json=payload(),
            headers={"Authorization": "Bearer static-client-token"},
        ).status_code
        == 403
    )


def test_retries_snapshot_conflicts_and_same_trip_new_snapshot(app_client):
    client, store = app_client
    first = prepare(client)
    retry = prepare(client)
    assert first["draft_id"] == retry["draft_id"]
    assert first["snapshot_sha256"] == retry["snapshot_sha256"]
    changed = payload()
    changed["answers"]["notes"] = "Changed after preparation"
    assert (
        client.post(BASE, json=changed, headers=auth()).status_code == 409
    ), "changed snapshot must conflict"
    assert (
        client.post(BASE, json=payload(snapshot_version="trip-v8"), headers=auth()).status_code
        == 409
    )
    assert lookup(client, version="trip-v8").status_code == 409
    second = prepare(client, handoff_id="handoff-456", snapshot_version="trip-v8")
    assert first["draft_id"] != second["draft_id"]
    executions = []
    for item in [first, second]:
        assert (
            client.post(f"/portal/review/{item['draft_id']}/submit", headers=auth()).status_code
            == 200
        )
        executions.append(
            lookup(client, handoff=item["handoff_id"], version=item["snapshot_version"]).json()[
                "execution_id"
            ]
        )
    assert len(set(executions)) == 2, "distinct snapshots must not share an execution"
    assert len(store.list_manager_reviews()) == 2


def test_browser_capability_is_view_only_and_cannot_read_status(app_client):
    client, _ = app_client
    first = prepare(client)
    session = client.post(
        f"{BASE}/handoff-123/browser-session?snapshot_version=trip-v7", headers=auth()
    )
    assert session.status_code == 200
    token = session.json()["handoff_token"]
    response = client.post(
        "/portal/handoff/receipt", data={"handoff_token": token}, follow_redirects=False
    )
    assert response.status_code == 303
    assert token not in response.headers["location"]
    assert client.get(response.headers["location"]).status_code == 200
    assert client.get(f"{BASE}/handoff-123?snapshot_version=trip-v7").status_code == 401
    assert client.post(f"/portal/review/{first['draft_id']}/submit").status_code == 401
    assert (
        client.post("/portal/handoff/receipt", data={"handoff_token": token + "x"}).status_code
        == 401
    )
    assert session.headers["cache-control"] == "no-store"
    assert lookup(client).headers["cache-control"] == "no-store"


def test_cross_instance_concurrent_retries_keep_one_persisted_draft(app_client, tmp_path):
    client, store = app_client
    other = PlannerProposalStore(state_path=tmp_path / "receipts.sqlite3")
    second = TestClient(create_app(other))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(prepare, [client, second]))
    assert results[0]["draft_id"] == results[1]["draft_id"]
    assert len(store.portal_drafts_by_id) == 1


def test_receipt_cannot_be_evicted_by_unrelated_draft_creation(app_client, monkeypatch):
    client, store = app_client
    first = prepare(client)
    monkeypatch.setattr("travel_plan_permission.http_service._PORTAL_MAX_DRAFTS", 1)
    response = client.post(BASE, json=payload(handoff_id="handoff-new"), headers=auth())
    assert response.status_code == 503, "capacity exhaustion must preserve existing receipt"
    assert lookup(client).json()["draft_id"] == first["draft_id"]
    with pytest.raises(Exception) as exc:
        store.save_portal_draft(_portal_form_payload())
    assert exc.value.status_code == 503


@pytest.mark.parametrize(
    "changes",
    [
        {"handoff_id": "x" * 81},
        {"snapshot_version": "bad/value"},
        {"answers": {"unknown_field": "ignored?"}},
        {"answers": {"notes": "x" * 65537}},
    ],
)
def test_bounded_invalid_input_cannot_create_a_receipt(app_client, changes):
    client, store = app_client
    assert client.post(BASE, json=payload(**changes), headers=auth()).status_code == 422
    assert not store.portal_drafts_by_id


def test_oidc_signed_tokens_validate_issuer_audience_and_namespace(app_client, monkeypatch):
    import json
    from datetime import UTC, datetime, timedelta

    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    from travel_plan_permission import planner_auth

    from .test_http_service import _serve_jwks

    client, _ = app_client
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    jwk.update({"kid": "receipt-test", "alg": "RS256", "use": "sig"})
    issuer = "https://issuer.example/tenant-a"

    def headers(subject="alice", iss=issuer, aud="trip-planner"):
        now = datetime.now(UTC)
        token = jwt.encode(
            {
                "sub": subject,
                "iss": iss,
                "aud": aud,
                "exp": now + timedelta(minutes=5),
                "nbf": now - timedelta(seconds=5),
            },
            private,
            algorithm="RS256",
            headers={"kid": "receipt-test"},
        )
        return {"Authorization": "Bearer " + token}

    with _serve_jwks({"keys": [jwk]}) as jwks_url:
        planner_auth._JWKS_CACHE.clear()
        monkeypatch.setenv("TPP_AUTH_MODE", "oidc")
        monkeypatch.setenv("TPP_OIDC_AUDIENCE", "trip-planner")
        monkeypatch.setenv("TPP_OIDC_ISSUER", issuer)
        monkeypatch.setenv("TPP_OIDC_JWKS_URL", jwks_url)
        prepared = client.post(BASE, json=payload(), headers=headers())
        assert prepared.status_code == 200, prepared.text
        assert lookup(client, headers=headers()).status_code == 200
        assert lookup(client, headers=headers(subject="bob")).status_code == 404
        assert (
            lookup(client, headers=headers(iss="https://issuer.example/tenant-b")).status_code
            == 401
        )
        assert lookup(client, headers=headers(aud="different-app")).status_code == 401
        # Even a later valid tenant-B configuration cannot reuse tenant-A subject ownership.
        monkeypatch.setenv("TPP_OIDC_ISSUER", "https://issuer.example/tenant-b")
        assert (
            lookup(client, headers=headers(iss="https://issuer.example/tenant-b")).status_code
            == 404
        ), "tenant namespace must remain isolated"


@pytest.mark.parametrize("failure", ["failed", "unavailable"])
def test_unaccepted_submission_cannot_create_request_or_review(app_client, monkeypatch, failure):
    from travel_plan_permission import http_service

    client, store = app_client
    draft = prepare(client)
    submit = http_service.submit_proposal

    def unaccepted(plan, request):
        # Inject a transport/policy result after real ASGI auth and preflight validation.
        return submit(plan, request).model_copy(update={"submission_status": failure})

    monkeypatch.setattr(http_service, "submit_proposal", unaccepted)
    response = client.post(f"/portal/review/{draft['draft_id']}/submit", headers=auth())
    assert response.status_code == (503 if failure == "unavailable" else 409)
    receipt = lookup(client).json()
    assert receipt["state"] == "prepared", "unaccepted submission must not become a request"
    assert receipt["request_id"] is None and receipt["review_id"] is None
    assert store.proposals_by_execution_id == {} and store.list_manager_reviews() == []


def test_backend_failure_cannot_be_reported_as_missing_or_prepared(app_client, monkeypatch):
    client, store = app_client
    prepare(client)

    def unavailable(*_args):
        raise OSError("backend unavailable")

    monkeypatch.setattr(store, "lookup_portal_receipt", unavailable)
    result = lookup(TestClient(create_app(store), raise_server_exceptions=False))
    assert result.status_code >= 500
    assert "prepared" not in result.text and "decision_recorded" not in result.text


def test_legacy_review_and_execution_routes_cannot_bypass_receipt_ownership(app_client):
    client, store = app_client
    draft = prepare(client)
    assert (
        client.post(f"/portal/review/{draft['draft_id']}/submit", headers=auth()).status_code == 200
    )
    pending = lookup(client).json()
    foreign = auth("traveler-b")
    review_id, execution = pending["review_id"], pending["execution_id"]
    assert client.get(f"/portal/manager/reviews/{review_id}", headers=foreign).status_code == 404
    queue = client.get("/portal/manager/reviews", headers=foreign)
    assert queue.status_code == 200 and review_id not in queue.text
    assert (
        client.get(
            f"/portal/review/{draft['draft_id']}/artifacts/request_xlsx",
            headers=foreign,
        ).status_code
        == 404
    )
    stored = store.lookup_submission(execution)
    assert (
        client.get(
            f"/api/planner/proposals/{stored.request.proposal_id}/executions/{execution}",
            headers=foreign,
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/planner/executions/{execution}/evaluation-result", headers=foreign
        ).status_code
        == 404
    )


class _AsgiTransport:
    """Route the typed planner client through the real ASGI app."""

    def __init__(self, client):
        self.client = client

    def __call__(self, method, url, headers, json_body, _timeout):
        path = url.removeprefix("http://tpp.test")
        response = self.client.request(method, path, headers=headers, json=json_body)
        try:
            body = response.json()
        except ValueError:
            body = None
        return PlannerJsonResponse(status_code=response.status_code, body=body, text=response.text)


def _planner(client, subject="traveler-a"):
    token = auth(subject)["Authorization"].removeprefix("Bearer ")
    return TravelPlanPermissionClient(
        base_url="http://tpp.test", token=token, transport=_AsgiTransport(client)
    )


@pytest.fixture(params=[True, False], ids=["receipt", "legacy"])
def approved_submission(app_client, request):
    client, store = app_client
    draft = prepare(client)
    assert (
        client.post(f"/portal/review/{draft['draft_id']}/submit", headers=auth()).status_code == 200
    )
    pending = lookup(client).json()
    response = client.post(
        f"/portal/manager/reviews/{pending['review_id']}/decision",
        headers=auth("manager", (Permission.APPROVE,)),
        data={"action": "approve", "rationale": "Approve this submitted snapshot only"},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    if not request.param:
        # Exercise legacy submissions without an immutable handoff receipt too.
        stored_draft = store.portal_drafts_by_id[draft["draft_id"]]
        store.portal_drafts_by_id[draft["draft_id"]] = replace(stored_draft, receipt_binding=None)
        store._persist_state()
    return client, store, pending, store.lookup_submission(pending["execution_id"])


@pytest.mark.parametrize("changed_field", ["trip_plan", "draft_id", "missing_draft_id"])
def test_bound_execution_rejects_changed_replay(approved_submission, tmp_path, changed_field):
    client, store, pending, original = approved_submission
    body = {
        "trip_plan": original.trip_plan.model_dump(mode="json"),
        "request": original.request.model_dump(mode="json"),
    }
    # An identical replay stays accepted, without replacing the saved response.
    assert client.post("/api/planner/proposals", headers=auth(), json=body).status_code == 200
    if changed_field == "trip_plan":
        body["trip_plan"]["purpose"] = "A different trip purpose after approval"
    elif changed_field == "draft_id":
        body["request"]["payload"]["draft_id"] = "another-draft"
    else:
        del body["request"]["payload"]["draft_id"]
    replay = client.post("/api/planner/proposals", headers=auth(), json=body)
    assert replay.status_code == 409, replay.text
    assert store.lookup_submission(pending["execution_id"]) == original
    assert store.lookup_trip_plan(original.trip_plan.trip_id) == original.trip_plan
    store.close()
    reloaded = PlannerProposalStore(state_path=tmp_path / "receipts.sqlite3")
    try:
        assert reloaded.lookup_submission(pending["execution_id"]) == original
        status = _planner(TestClient(create_app(reloaded))).poll_status(
            proposal_id=original.request.proposal_id, execution_id=pending["execution_id"]
        )
        assert status.proposal_status.status.value == "approved"
        assert len(status.proposal_status.approval_history) == 1
    finally:
        reloaded.close()


def test_projection_rejects_mismatched_review_snapshot(approved_submission, tmp_path):
    client, store, pending, original = approved_submission
    # Simulate a legacy overwritten snapshot already persisted before this guard.
    stored = store.proposals_by_execution_id[pending["execution_id"]]
    stored.trip_plan.purpose = "Changed content with the same trip and execution IDs"
    store._persist_state()
    store.close()
    reloaded = PlannerProposalStore(state_path=tmp_path / "receipts.sqlite3")
    try:
        restarted = TestClient(create_app(reloaded))
        for url in (
            f"/api/planner/proposals/{original.request.proposal_id}/executions/{pending['execution_id']}",
            f"/api/planner/executions/{pending['execution_id']}/evaluation-result",
        ):
            response = restarted.get(url, headers=auth())
            assert response.status_code == 409, response.text
    finally:
        reloaded.close()


@pytest.mark.parametrize(
    ("action", "trip_status", "submission_status", "terminal"),
    [
        ("approve", "approved", "succeeded", True),
        ("reject", "rejected", "failed", True),
        # request_changes maps onto the canonical "submitted" TripPlan status.
        ("request_changes", "submitted", "pending", False),
    ],
)
def test_manager_decision_reaches_typed_planner_readback(
    app_client, tmp_path, action, trip_status, submission_status, terminal
):
    client, store = app_client
    draft = prepare(client)
    submitted = client.post(f"/portal/review/{draft['draft_id']}/submit", headers=auth())
    assert submitted.status_code == 200, submitted.text
    pending = lookup(client).json()
    execution = pending["execution_id"]
    proposal_id = store.lookup_submission(execution).request.proposal_id
    planner = _planner(client)
    before = planner.poll_status(proposal_id=proposal_id, execution_id=execution)
    assert before.submission_status == "pending"
    assert before.proposal_status.approval_history == ()
    evaluation_before = planner.fetch_evaluation_result(execution_id=execution)

    rationale = f"Manager {action} rationale"
    decision = client.post(
        f"/portal/manager/reviews/{pending['review_id']}/decision",
        headers=auth("manager", (Permission.APPROVE,)),
        data={"action": action, "rationale": rationale},
        follow_redirects=False,
    )
    assert decision.status_code == 303, decision.text

    def assert_projected(reader):
        status_response = reader.poll_status(proposal_id=proposal_id, execution_id=execution)
        assert status_response.submission_status == submission_status
        assert status_response.execution_status.terminal is terminal
        assert status_response.proposal_status.status.value == trip_status
        history = status_response.proposal_status.approval_history
        assert len(history) == 1, "planner must see the authoritative decision"
        expected_decision = {
            "approve": "approved",
            "reject": "rejected",
            "request_changes": "flagged",
        }[action]
        assert history[0].outcome == expected_decision
        assert history[0].approver_id == "manager"
        assert history[0].level == "manager"
        assert history[0].justification == rationale
        evaluation = reader.fetch_evaluation_result(execution_id=execution)
        if action == "reject":
            assert evaluation.exception_requirements == []
            assert evaluation.outcome == "non_compliant"
        else:
            # Approval is not policy compliance; the verdict must not move.
            assert evaluation.outcome == evaluation_before.outcome
        return status_response

    recorded = assert_projected(planner)
    with pytest.raises(PlannerHttpError) as foreign:
        _planner(client, "traveler-b").poll_status(proposal_id=proposal_id, execution_id=execution)
    assert foreign.value.status_code == 404

    store.close()
    reloaded = PlannerProposalStore(state_path=tmp_path / "receipts.sqlite3")
    restarted_client = TestClient(create_app(reloaded))
    restarted = assert_projected(_planner(restarted_client))
    assert restarted.result_payload["execution_id"] == execution
    assert restarted.proposal_status.proposal_id == recorded.proposal_status.proposal_id
    # The submitted snapshot itself stays immutable; only the projection moves.
    snapshot = reloaded.lookup_submission(execution).trip_plan
    assert snapshot.approval_history == ()
    with pytest.raises(PlannerHttpError) as foreign_after_restart:
        _planner(restarted_client, "traveler-b").fetch_evaluation_result(execution_id=execution)
    assert foreign_after_restart.value.status_code == 404


def _exception_form():
    return {
        "exception_type": "advance_booking",
        "amount": "250",
        "justification": "Documented business need for this routed exception tier. " * 2,
        "supporting_doc": "docs/exception-policy.md",
    }


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_exception_decision_reaches_typed_planner_readback(app_client, tmp_path, decision):
    client, store = app_client
    draft = prepare(client)
    draft_id = draft["draft_id"]
    created = client.post(
        f"/portal/review/{draft_id}/exceptions",
        headers=auth(),
        data=_exception_form(),
        follow_redirects=False,
    )
    assert created.status_code == 303, created.text
    assert client.post(f"/portal/review/{draft_id}/submit", headers=auth()).status_code == 200
    execution = lookup(client).json()["execution_id"]
    planner = _planner(client)
    before = planner.fetch_evaluation_result(execution_id=execution)
    assert [r.status for r in before.exception_requirements] == ["pending"]

    decided = client.post(
        f"/portal/admin/exceptions/{draft_id}/0/decision?actor_role=approver",
        headers=auth("approver", (Permission.VIEW, Permission.APPROVE)),
        data={"decision": decision, "notes": "Exception decision"},
        follow_redirects=False,
    )
    assert decided.status_code == 303, decided.text
    expected = [] if decision == "approve" else ["rejected"]

    def assert_projected(reader):
        result = reader.fetch_evaluation_result(execution_id=execution)
        assert [r.status for r in result.exception_requirements] == expected

    assert_projected(planner)
    with pytest.raises(PlannerHttpError) as foreign:
        _planner(client, "traveler-b").fetch_evaluation_result(execution_id=execution)
    assert foreign.value.status_code == 404
    store.close()
    reloaded = PlannerProposalStore(state_path=tmp_path / "receipts.sqlite3")
    assert_projected(_planner(TestClient(create_app(reloaded))))
    stored = reloaded.lookup_submission(execution).trip_plan
    assert stored.exception_requests == []
