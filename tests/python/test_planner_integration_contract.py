from __future__ import annotations

import json
from pathlib import Path

from travel_plan_permission import PlannerPolicySnapshotResponse


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "planner"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def test_policy_snapshot_fixture_matches_public_snapshot_contract() -> None:
    payload = _load_fixture("policy_snapshot.json")

    snapshot = PlannerPolicySnapshotResponse.model_validate(payload)

    assert snapshot.planner_id == "trip-planner"
    assert snapshot.auth_scheme == "service_token"
    assert snapshot.metadata.policy_version
    assert snapshot.metadata.approval_rules_version
    assert snapshot.metadata.provider_registry_version == "2024.09"
    assert any(rule.rule_id == "fare_evidence" for rule in snapshot.policy_rules)
    assert any(
        requirement.category == "airfare"
        for requirement in snapshot.booking_channel_requirements
    )


def test_proposal_submission_fixture_carries_snapshot_and_transport_metadata() -> None:
    snapshot = _load_fixture("policy_snapshot.json")
    submission = _load_fixture("proposal_submission.json")

    assert submission["planner_id"] == "trip-planner"
    assert submission["planner_version"] == snapshot["planner_version"]
    assert submission["auth"]["scheme"] == snapshot["auth_scheme"]
    assert submission["auth"]["header_name"] == "Authorization"
    assert (
        submission["policy_snapshot"]["policy_version"]
        == snapshot["metadata"]["policy_version"]
    )
    assert (
        submission["policy_snapshot"]["approval_rules_version"]
        == snapshot["metadata"]["approval_rules_version"]
    )
    assert (
        submission["policy_snapshot"]["provider_registry_version"]
        == snapshot["metadata"]["provider_registry_version"]
    )

    proposal = submission["proposal"]
    assert proposal["proposal_id"] == submission["proposal_id"]
    assert proposal["trip_id"] == submission["trip_id"]
    assert proposal["mode"] == "business"
    assert proposal["selected_options"]
    assert proposal["booking_channel_summaries"][0]["approved"] is True


def test_status_fixture_links_submission_to_evaluation_result() -> None:
    submission = _load_fixture("proposal_submission.json")
    status = _load_fixture("proposal_status.json")
    evaluation = _load_fixture("evaluation_result.json")

    assert status["proposal_id"] == submission["proposal_id"]
    assert status["trip_id"] == submission["trip_id"]
    assert status["planner_id"] == submission["planner_id"]
    assert status["planner_version"] == submission["planner_version"]
    assert status["status"] == "evaluated"
    assert status["evaluation_id"] == evaluation["evaluation_id"]
    assert status["evaluation_status"] == evaluation["status"]
    assert status["evaluation_result_url"].endswith(evaluation["evaluation_id"])


def test_evaluation_result_fixture_matches_business_contract_shape() -> None:
    evaluation = _load_fixture("evaluation_result.json")

    assert evaluation["status"] in {"compliant", "non_compliant", "exception_required"}
    assert evaluation["failure_reasons"]
    assert evaluation["failure_reasons"][0]["severity"] in {"warning", "blocking"}
    assert 0.0 <= evaluation["compliance_score"] <= 1.0
    assert evaluation["preferred_alternatives"][0]["comparable_ref"]
    assert isinstance(evaluation["exception_guidance"], list)
    assert isinstance(evaluation["notes"], list)
