from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from travel_plan_permission.http_service import (
    PlannerProposalStore,
    PortalArtifact,
    create_app,
)
from travel_plan_permission.policy_api import PolicyCheckResult, PolicyIssue
from travel_plan_permission import portal_review

from tests.python.test_http_service import (
    AUTH_HEADER,
    _create_portal_draft,
    _get_portal_review,
    _set_runtime_env,
)


def _blocking_policy_result() -> PolicyCheckResult:
    return PolicyCheckResult(
        status="fail",
        issues=[
            PolicyIssue(
                code="blocking_rule",
                message="Blocking issue.",
                severity="error",
            )
        ],
        policy_version="v1",
    )


def _advisory_policy_result() -> PolicyCheckResult:
    return PolicyCheckResult(
        status="pass",
        issues=[
            PolicyIssue(
                code="advisory_rule",
                message="Advisory issue.",
                severity="warning",
            )
        ],
        policy_version="v1",
    )


def test_workbook_is_not_generated_for_a_blocking_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_runtime_env(monkeypatch)
    monkeypatch.setattr(
        portal_review,
        "check_trip_plan",
        lambda _plan: _blocking_policy_result(),
    )
    client = TestClient(create_app(PlannerProposalStore()))
    draft_id, _location = _create_portal_draft(client)
    response = _get_portal_review(client, draft_id)

    assert response.status_code == 200
    assert "Generated artifacts" not in response.text
    assert "blocking_rule" in response.text


def test_workbook_download_refuses_a_blocking_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_runtime_env(monkeypatch)
    store = PlannerProposalStore()
    client = TestClient(create_app(store))
    draft_id, _location = _create_portal_draft(client)
    store.cache_portal_artifacts(
        draft_id,
        {
            "itinerary": PortalArtifact(
                filename="itinerary.xlsx",
                content=b"legacy",
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    monkeypatch.setattr(
        portal_review,
        "check_trip_plan",
        lambda _plan: _blocking_policy_result(),
    )

    response = client.get(
        f"/portal/review/{draft_id}/artifacts/itinerary",
        headers=AUTH_HEADER,
    )

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["blocking_codes"] == ["blocking_rule"]


def test_advisory_findings_do_not_block_the_workbook(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_runtime_env(monkeypatch)
    monkeypatch.setattr(
        portal_review,
        "check_trip_plan",
        lambda _plan: _advisory_policy_result(),
    )
    client = TestClient(create_app(PlannerProposalStore()))
    draft_id, _location = _create_portal_draft(client)
    response = _get_portal_review(client, draft_id)

    assert response.status_code == 200
    assert "Generated artifacts" in response.text

    itinerary = client.get(
        f"/portal/review/{draft_id}/artifacts/itinerary",
        headers=AUTH_HEADER,
    )
    assert itinerary.status_code == 200
