from __future__ import annotations

import json
from pathlib import Path

from travel_plan_permission.canonical import load_trip_plan_input
from travel_plan_permission.policy_api import (
    PlannerPolicySnapshotRequest,
    PlannerProposalEvaluationRequest,
    PlannerProposalSubmissionRequest,
    get_evaluation_result,
    get_policy_snapshot,
    submit_proposal,
)
from travel_plan_permission.review_workflow import (
    ManagerReviewDecision,
    ManagerReviewStatus,
    ReviewWorkflowStore,
)


def _load_trip_plan() -> tuple[dict[str, object], object]:
    fixture_path = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "planner_integration"
        / "proposal_submission.json"
    )
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    trip_input = load_trip_plan_input(payload)
    return payload, trip_input.plan


def test_review_workflow_store_persists_and_reloads_manager_decisions(tmp_path: Path) -> None:
    _, trip_plan = _load_trip_plan()
    policy_snapshot = get_policy_snapshot(
        trip_plan,
        PlannerPolicySnapshotRequest(trip_id=trip_plan.trip_id),
    )
    submission_request = PlannerProposalSubmissionRequest(
        trip_id=trip_plan.trip_id,
        proposal_id=f"{trip_plan.trip_id.lower()}-portal-request",
        proposal_version="portal-v1",
        payload={"channel": "workflow-portal"},
    )
    submission_response = submit_proposal(trip_plan, submission_request)
    execution_id = str(submission_response.result_payload["execution_id"])
    evaluation_result = get_evaluation_result(
        trip_plan,
        PlannerProposalEvaluationRequest(
            trip_id=trip_plan.trip_id,
            proposal_id=submission_request.proposal_id,
            proposal_version=submission_request.proposal_version,
            execution_id=execution_id,
        ),
    )

    store = ReviewWorkflowStore(tmp_path / "reviews")
    created = store.create_record(
        draft_id="draft-123",
        portal_answers={"traveler_name": trip_plan.traveler_name},
        trip_plan=trip_plan,
        policy_snapshot=policy_snapshot,
        evaluation_result=evaluation_result,
        submission_response=submission_response,
    )

    assert created.status == ManagerReviewStatus.PENDING
    assert (tmp_path / "reviews" / f"{created.request_id}.json").exists()

    updated = store.record_manager_decision(
        created.request_id,
        decision=ManagerReviewDecision.APPROVE,
        reviewer_id="manager@example.edu",
        rationale="Policy posture is acceptable for the current budget and routing.",
    )

    assert updated.status == ManagerReviewStatus.APPROVED
    assert len(updated.history) == 1
    assert updated.trip_plan.approval_history[-1].outcome.value == "approved"

    reloaded = store.get_record(created.request_id)
    assert reloaded is not None
    assert reloaded.status == ManagerReviewStatus.APPROVED
    assert reloaded.history[0].reviewer_id == "manager@example.edu"
