from __future__ import annotations

import json
from pathlib import Path

from travel_plan_permission.models import TripPlan
from travel_plan_permission.policy_api import (
    PlannerPolicySnapshot,
    PlannerPolicySnapshotRequest,
    PolicyCheckResult,
)

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "planner_integration"
CONTRACT_DOC = Path(__file__).resolve().parents[2] / "docs" / "contracts" / "planner-integration.md"


def _load_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def test_planner_contract_doc_references_all_supported_fixtures() -> None:
    contract_text = CONTRACT_DOC.read_text(encoding="utf-8")

    assert "Policy snapshot fetch" in contract_text
    assert "Proposal submission" in contract_text
    assert "Proposal status readback" in contract_text
    assert "Policy evaluation result handling" in contract_text

    expected_paths = [
        "tests/fixtures/planner_integration/policy_snapshot_request.json",
        "tests/fixtures/planner_integration/policy_snapshot_response.json",
        "tests/fixtures/planner_integration/proposal_submission.json",
        "tests/fixtures/planner_integration/proposal_status.json",
        "tests/fixtures/planner_integration/evaluation_result.json",
    ]
    for expected_path in expected_paths:
        assert expected_path in contract_text


def test_policy_snapshot_request_fixture_matches_request_model() -> None:
    request = PlannerPolicySnapshotRequest.model_validate(
        _load_fixture("policy_snapshot_request.json")
    )

    assert request.trip_id == "TRIP-PLANNER-2001"
    assert request.known_policy_version == "d7a6d25a"
    assert request.invalidate_reason is None


def test_policy_snapshot_response_fixture_matches_response_model() -> None:
    response = PlannerPolicySnapshot.model_validate(
        _load_fixture("policy_snapshot_response.json")
    )

    assert response.freshness == "current"
    assert response.auth.required_permission == "view"
    assert response.versioning.compatible_with_planner_cache is True


def test_proposal_submission_fixture_matches_trip_plan_model() -> None:
    submission = TripPlan.model_validate(_load_fixture("proposal_submission.json"))

    assert submission.status.value == "submitted"
    assert submission.selected_providers["airfare"] == "Blue Skies Airlines"


def test_proposal_status_fixture_matches_trip_plan_model() -> None:
    status_payload = TripPlan.model_validate(_load_fixture("proposal_status.json"))

    assert status_payload.status.value == "approved"
    assert len(status_payload.approval_history) == 1
    assert status_payload.approval_history[0].new_status.value == "approved"


def test_evaluation_result_fixture_matches_policy_check_model() -> None:
    evaluation = PolicyCheckResult.model_validate(_load_fixture("evaluation_result.json"))

    assert evaluation.status == "fail"
    assert {issue.code for issue in evaluation.issues} == {
        "fare_comparison",
        "fare_evidence",
    }
