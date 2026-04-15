"""Durable manager-review workflow records for portal-submitted requests."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from .models import ApprovalOutcome, TripPlan
from .policy_api import (
    PlannerBlockingIssue,
    PlannerExceptionRequirement,
    PlannerPolicySnapshot,
    PlannerProposalEvaluationResult,
    PlannerProposalOperationResponse,
)


class ManagerReviewStatus(StrEnum):
    """Lifecycle states for the persisted manager review workflow."""

    PENDING = "pending_manager_review"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    REJECTED = "rejected"


class ManagerReviewDecision(StrEnum):
    """Manager actions supported by the review workflow."""

    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"
    REJECT = "reject"


class ManagerReviewHistoryEntry(BaseModel):
    """Immutable audit entry for a manager decision."""

    decision: ManagerReviewDecision
    reviewer_id: str = Field(..., min_length=1)
    rationale: str = Field(..., min_length=5)
    decided_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    resulting_status: ManagerReviewStatus


class ManagerReviewRecord(BaseModel):
    """Persisted request-review state for manager queue and detail views."""

    request_id: str
    draft_id: str
    trip_id: str
    traveler_name: str
    business_purpose: str
    destination: str
    submitted_at: datetime
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: ManagerReviewStatus = ManagerReviewStatus.PENDING
    current_reviewer: str = "manager"
    portal_answers: dict[str, object] = Field(default_factory=dict)
    trip_plan: TripPlan
    policy_snapshot: PlannerPolicySnapshot
    evaluation_result: PlannerProposalEvaluationResult
    submission_response: PlannerProposalOperationResponse
    history: list[ManagerReviewHistoryEntry] = Field(default_factory=list)


class ReviewWorkflowStore:
    """File-backed store for portal-submitted manager review records."""

    def __init__(self, base_path: Path | None = None) -> None:
        default_root = Path(
            os.getenv("TPP_REVIEW_STORE_PATH", Path.cwd() / ".data" / "review-workflow")
        )
        self.base_path = Path(base_path) if base_path is not None else default_root
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _record_path(self, request_id: str) -> Path:
        return self.base_path / f"{request_id}.json"

    def _write_record(self, record: ManagerReviewRecord) -> None:
        path = self._record_path(record.request_id)
        payload = json.dumps(record.model_dump(mode="json"), indent=2, sort_keys=True)
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(payload, encoding="utf-8")
        tmp_path.replace(path)

    def save_record(self, record: ManagerReviewRecord) -> ManagerReviewRecord:
        """Persist a manager review record to disk."""

        saved = record.model_copy(update={"updated_at": datetime.now(UTC)}, deep=True)
        self._write_record(saved)
        return saved

    def create_record(
        self,
        *,
        draft_id: str,
        portal_answers: dict[str, object],
        trip_plan: TripPlan,
        policy_snapshot: PlannerPolicySnapshot,
        evaluation_result: PlannerProposalEvaluationResult,
        submission_response: PlannerProposalOperationResponse,
    ) -> ManagerReviewRecord:
        """Create and persist a new manager review record for a submitted draft."""

        destination = trip_plan.destination_city or trip_plan.destination
        record = ManagerReviewRecord(
            request_id=evaluation_result.execution_id,
            draft_id=draft_id,
            trip_id=trip_plan.trip_id,
            traveler_name=trip_plan.traveler_name,
            business_purpose=trip_plan.purpose,
            destination=destination,
            submitted_at=datetime.now(UTC),
            portal_answers=dict(portal_answers),
            trip_plan=trip_plan.model_copy(deep=True),
            policy_snapshot=policy_snapshot.model_copy(deep=True),
            evaluation_result=evaluation_result.model_copy(deep=True),
            submission_response=submission_response.model_copy(deep=True),
        )
        return self.save_record(record)

    def get_record(self, request_id: str) -> ManagerReviewRecord | None:
        """Load a persisted manager review record by identifier."""

        path = self._record_path(request_id)
        if not path.exists():
            return None
        return ManagerReviewRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def list_records(self) -> list[ManagerReviewRecord]:
        """Return persisted manager review records sorted by update time descending."""

        records = [
            ManagerReviewRecord.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(self.base_path.glob("*.json"))
        ]
        return sorted(records, key=lambda record: record.updated_at, reverse=True)

    def record_manager_decision(
        self,
        request_id: str,
        *,
        decision: ManagerReviewDecision,
        reviewer_id: str,
        rationale: str,
    ) -> ManagerReviewRecord:
        """Apply a manager decision, update trip approval history, and persist it."""

        record = self.get_record(request_id)
        if record is None:
            raise KeyError(request_id)

        rationale_text = rationale.strip()
        if len(rationale_text) < 5:
            raise ValueError("Manager decisions require rationale text.")

        if decision == ManagerReviewDecision.APPROVE:
            status = ManagerReviewStatus.APPROVED
            record.trip_plan.record_approval_decision(
                approver_id=reviewer_id,
                level="manager",
                outcome=ApprovalOutcome.APPROVED,
                justification=rationale_text,
            )
        elif decision == ManagerReviewDecision.REJECT:
            status = ManagerReviewStatus.REJECTED
            record.trip_plan.record_approval_decision(
                approver_id=reviewer_id,
                level="manager",
                outcome=ApprovalOutcome.REJECTED,
                justification=rationale_text,
            )
        else:
            status = ManagerReviewStatus.CHANGES_REQUESTED
            record.trip_plan.record_approval_decision(
                approver_id=reviewer_id,
                level="manager",
                outcome=ApprovalOutcome.FLAGGED,
            )

        history_entry = ManagerReviewHistoryEntry(
            decision=decision,
            reviewer_id=reviewer_id.strip(),
            rationale=rationale_text,
            resulting_status=status,
        )
        updated = record.model_copy(
            update={
                "status": status,
                "history": [*record.history, history_entry],
                "trip_plan": record.trip_plan,
            },
            deep=True,
        )
        return self.save_record(updated)


__all__ = [
    "ManagerReviewDecision",
    "ManagerReviewHistoryEntry",
    "ManagerReviewRecord",
    "ManagerReviewStatus",
    "ReviewWorkflowStore",
]
