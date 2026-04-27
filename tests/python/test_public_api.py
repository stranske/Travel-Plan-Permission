"""Tests for package public API exports."""

from __future__ import annotations

import importlib


def test_public_api_imports() -> None:
    """Package root should expose the documented API symbols."""
    travel_plan_permission = importlib.import_module("travel_plan_permission")

    from travel_plan_permission import (
        BusinessPolicyEffect,
        BusinessPolicyScore,
        PlannerBlockingIssue,
        PlannerEvaluationOutcome,
        PlannerExceptionRequirement,
        PlannerPreferredAlternative,
        PlannerProposalEvaluationRequest,
        PlannerProposalEvaluationResult,
        PlannerProposalOperationResponse,
        PlannerProposalStatusRequest,
        PlannerProposalSubmissionRequest,
        PlannerReoptimizationGuidance,
        PolicyCheckResult,
        PolicyCheckStatus,
        PolicyIssue,
        PolicyIssueSeverity,
        Receipt,
        ReconciliationResult,
        ReconciliationStatus,
        TripPlan,
        check_trip_plan,
        fill_travel_spreadsheet,
        get_evaluation_result,
        list_allowed_vendors,
        poll_execution_status,
        reconcile,
        render_travel_spreadsheet_bytes,
        submit_proposal,
    )

    required_exports = {
        "BusinessPolicyEffect",
        "BusinessPolicyScore",
        "PlannerBlockingIssue",
        "PlannerEvaluationOutcome",
        "PlannerExceptionRequirement",
        "PlannerPreferredAlternative",
        "PlannerProposalEvaluationRequest",
        "PlannerProposalEvaluationResult",
        "PlannerProposalOperationResponse",
        "PlannerProposalStatusRequest",
        "PlannerProposalSubmissionRequest",
        "PlannerReoptimizationGuidance",
        "PolicyCheckResult",
        "PolicyCheckStatus",
        "PolicyIssue",
        "PolicyIssueSeverity",
        "Receipt",
        "ReconciliationResult",
        "ReconciliationStatus",
        "TripPlan",
        "check_trip_plan",
        "fill_travel_spreadsheet",
        "get_evaluation_result",
        "render_travel_spreadsheet_bytes",
        "list_allowed_vendors",
        "poll_execution_status",
        "reconcile",
        "submit_proposal",
        "__version__",
    }
    assert required_exports.issubset(set(travel_plan_permission.__all__))
    assert travel_plan_permission.__version__
    assert TripPlan is not None
    assert BusinessPolicyEffect is not None
    assert BusinessPolicyScore is not None
    assert check_trip_plan is not None
    assert list_allowed_vendors is not None
    assert reconcile is not None
    assert fill_travel_spreadsheet is not None
    assert get_evaluation_result is not None
    assert render_travel_spreadsheet_bytes is not None
    assert submit_proposal is not None
    assert poll_execution_status is not None
    assert PlannerProposalEvaluationRequest is not None
    assert PlannerProposalEvaluationResult is not None
    assert PlannerProposalSubmissionRequest is not None
    assert PlannerProposalStatusRequest is not None
    assert PlannerProposalOperationResponse is not None
    assert PlannerBlockingIssue is not None
    assert PlannerPreferredAlternative is not None
    assert PlannerExceptionRequirement is not None
    assert PlannerReoptimizationGuidance is not None
    assert PlannerEvaluationOutcome is not None
    assert PolicyCheckResult is not None
    assert PolicyCheckStatus is not None
    assert PolicyIssue is not None
    assert PolicyIssueSeverity is not None
    assert ReconciliationResult is not None
    assert ReconciliationStatus is not None
    assert Receipt is not None
