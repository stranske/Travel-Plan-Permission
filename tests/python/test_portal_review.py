from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from tests.python.test_http_service import (
    AUTH_HEADER,
    _create_portal_draft,
    _get_portal_review,
    _seed_manager_review,
    _set_runtime_env,
)

from travel_plan_permission import portal_review
from travel_plan_permission.http_service import (
    PlannerProposalStore,
    PortalArtifact,
    create_app,
)
from travel_plan_permission.policy_api import PolicyCheckResult, PolicyIssue
from travel_plan_permission.review_workflow import (
    ReviewAction,
    ReviewStatus,
    apply_review_action,
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


@pytest.mark.parametrize("final_action", [ReviewAction.APPROVE, ReviewAction.REJECT])
@pytest.mark.parametrize("action", list(ReviewAction))
def test_finalized_review_rejects_all_actions(
    final_action: ReviewAction, action: ReviewAction
) -> None:
    review = _seed_manager_review(
        PlannerProposalStore(), status=ReviewStatus.PENDING_MANAGER_REVIEW
    )
    finalized = apply_review_action(
        review, action=final_action, actor_id="first-manager", rationale="Final decision."
    )
    before = deepcopy(finalized)

    with pytest.raises(ValueError, match="finalized reviews cannot be changed"):
        apply_review_action(
            finalized, action=action, actor_id="second-manager", rationale="Repeated decision."
        )

    assert finalized == before
    assert len(finalized.history) == 1
    assert finalized.trip_plan.approval_history[-1].approver_id == "first-manager"


@pytest.mark.parametrize("action", list(ReviewAction))
def test_changes_requested_review_can_still_receive_actions(action: ReviewAction) -> None:
    review = _seed_manager_review(
        PlannerProposalStore(), status=ReviewStatus.PENDING_MANAGER_REVIEW
    )
    changed = apply_review_action(
        review, action=ReviewAction.REQUEST_CHANGES, actor_id="manager", rationale="Revise costs."
    )
    updated = apply_review_action(
        changed, action=action, actor_id="manager", rationale="Reviewed revised costs."
    )

    assert updated.history[-1].event_type == action.value
    assert len(updated.history) == 2
    assert len(updated.trip_plan.approval_history) == len(changed.trip_plan.approval_history) + 1
