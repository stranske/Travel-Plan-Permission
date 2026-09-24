"""Focused helpers for planner execution-status responses."""

from __future__ import annotations

from datetime import datetime

from .policy_contract_models import (
    PlannerErrorRecord,
    PlannerProposalExecutionStatus,
    PlannerProposalOperationResponse,
    PolicyCheckResult,
)


def blocking_codes(result: PolicyCheckResult) -> list[str]:
    """Return codes for policy issues that block proposal submission."""

    return [
        issue.code
        for issue in result.issues
        if issue.severity == "error"
        and (issue.context or {}).get("blocking") is not False
    ]


def blocked_policy_response(
    response: PlannerProposalOperationResponse,
    codes: list[str],
    event_time: datetime,
) -> PlannerProposalOperationResponse:
    """Replace a pending-approval response with its completed blocking verdict."""

    payload = dict(response.result_payload)
    payload.pop("approval_state", None)
    payload.update(
        queue_state="blocked_by_policy",
        evaluation_state="completed",
        blocking_codes=codes,
    )
    return response.model_copy(
        update={
            "submission_status": "failed",
            "execution_status": PlannerProposalExecutionStatus(
                state="failed",
                terminal=True,
                summary=(
                    "Policy evaluation finished; the proposal is blocked and must be "
                    "updated before approval."
                ),
                external_status="409 Conflict",
                updated_at=event_time,
            ),
            "result_payload": payload,
            "error": PlannerErrorRecord(
                code="proposal_blocked_by_policy",
                message="The proposal has blocking policy violations and cannot proceed.",
                category="policy",
                retryable=False,
                details={"blocking_codes": codes},
            ),
            "retry": None,
        }
    )
