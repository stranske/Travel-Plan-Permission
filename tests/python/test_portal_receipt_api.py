"""Real ASGI/auth/persistence contract for owner-scoped portal receipts."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from travel_plan_permission.http_service import PlannerProposalStore, create_app
from travel_plan_permission.planner_auth import mint_bootstrap_token
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
    assert (
        pending["state"] == "pending_review"
    ), "submission must use the persisted manager queue"
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
    assert (
        recorded["state"] == "decision_recorded" and recorded["decision"] == "approved"
    )
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
    assert (
        after["decision"] == before["decision"]
    ), "retry must preserve the recorded decision"
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
        lookup(
            client, headers=auth("manager", (Permission.VIEW, Permission.APPROVE))
        ).status_code
        == 404
    )
    own = client.post(BASE, json=payload(), headers=foreign).json()
    assert own["draft_id"] != prepared["draft_id"]


@pytest.mark.parametrize(
    "headers,status", [({}, 401), ({"Authorization": "Bearer tampered"}, 503)]
)
def test_actual_auth_rejects_absent_and_invalid_credentials(
    app_client, headers, status
):
    client, _ = app_client
    assert client.post(BASE, json=payload(), headers=headers).status_code == status
    assert (
        client.get(
            f"{BASE}/handoff-123?snapshot_version=trip-v7", headers=headers
        ).status_code
        == status
    )


def test_permissions_and_wrong_provider_are_checked_by_real_auth(app_client):
    client, _ = app_client
    assert (
        client.post(
            BASE, json=payload(), headers=auth(permissions=(Permission.VIEW,))
        ).status_code
        == 403
    )
    prepare(client)
    assert (
        lookup(client, headers=auth(permissions=(Permission.CREATE,))).status_code
        == 403
    )
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
        client.post(
            BASE, json=payload(snapshot_version="trip-v8"), headers=auth()
        ).status_code
        == 409
    )
    assert lookup(client, version="trip-v8").status_code == 409
    second = prepare(client, handoff_id="handoff-456", snapshot_version="trip-v8")
    assert first["draft_id"] != second["draft_id"]
    executions = []
    for item in [first, second]:
        assert (
            client.post(
                f"/portal/review/{item['draft_id']}/submit", headers=auth()
            ).status_code
            == 200
        )
        executions.append(
            lookup(
                client, handoff=item["handoff_id"], version=item["snapshot_version"]
            ).json()["execution_id"]
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
        client.post(
            "/portal/handoff/receipt", data={"handoff_token": token + "x"}
        ).status_code
        == 401
    )
    assert session.headers["cache-control"] == "no-store"
    assert lookup(client).headers["cache-control"] == "no-store"


def test_cross_instance_concurrent_retries_keep_one_persisted_draft(
    app_client, tmp_path
):
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
    assert (
        response.status_code == 503
    ), "capacity exhaustion must preserve existing receipt"
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


def test_oidc_signed_tokens_validate_issuer_audience_and_namespace(
    app_client, monkeypatch
):
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
            lookup(
                client, headers=headers(iss="https://issuer.example/tenant-b")
            ).status_code
            == 401
        )
        assert lookup(client, headers=headers(aud="different-app")).status_code == 401
        # Even a later valid tenant-B configuration cannot reuse tenant-A subject ownership.
        monkeypatch.setenv("TPP_OIDC_ISSUER", "https://issuer.example/tenant-b")
        assert (
            lookup(
                client, headers=headers(iss="https://issuer.example/tenant-b")
            ).status_code
            == 404
        ), "tenant namespace must remain isolated"


@pytest.mark.parametrize("failure", ["failed", "unavailable"])
def test_unaccepted_submission_cannot_create_request_or_review(
    app_client, monkeypatch, failure
):
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
    assert (
        receipt["state"] == "prepared"
    ), "unaccepted submission must not become a request"
    assert receipt["request_id"] is None and receipt["review_id"] is None
    assert store.proposals_by_execution_id == {} and store.list_manager_reviews() == []


def test_backend_failure_cannot_be_reported_as_missing_or_prepared(
    app_client, monkeypatch
):
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
        client.post(
            f"/portal/review/{draft['draft_id']}/submit", headers=auth()
        ).status_code
        == 200
    )
    pending = lookup(client).json()
    foreign = auth("traveler-b")
    review_id, execution = pending["review_id"], pending["execution_id"]
    assert (
        client.get(f"/portal/manager/reviews/{review_id}", headers=foreign).status_code
        == 404
    )
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
