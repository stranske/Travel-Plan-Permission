"""Persisted in-runtime review workflow state for manager approval UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from .models import ApprovalOutcome, TripPlan, TripStatus
from .policy_api import PlannerPolicySnapshot, PolicyCheckResult


class ReviewAction(StrEnum):
    """Supported manager review actions."""

    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_CHANGES = "request_changes"


class ReviewStatus(StrEnum):
    """Lifecycle states for a persisted manager review."""

    PENDING_MANAGER_REVIEW = "pending_manager_review"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True)
class ReviewHistoryEvent:
    """Immutable review workflow event."""

    event_type: str
    actor_id: str
    timestamp: datetime
    status: ReviewStatus
    rationale: str | None = None


@dataclass(frozen=True)
class ReviewRequest:
    """Persisted review request and its current decision state."""

    review_id: str
    draft_id: str
    trip_plan: TripPlan
    policy_snapshot: PlannerPolicySnapshot
    policy_result: PolicyCheckResult
    status: ReviewStatus
    submitted_at: datetime
    updated_at: datetime
    history: tuple[ReviewHistoryEvent, ...] = ()


def _now() -> datetime:
    return datetime.now(UTC)


def create_review_request(
    *,
    draft_id: str,
    trip_plan: TripPlan,
    policy_snapshot: PlannerPolicySnapshot,
    policy_result: PolicyCheckResult,
) -> ReviewRequest:
    """Create a persisted manager review request from a submitted trip."""

    submitted_at = _now()
    plan = trip_plan.model_copy(deep=True)
    plan.status = TripStatus.SUBMITTED
    history = (
        ReviewHistoryEvent(
            event_type="submitted",
            actor_id="workflow-portal",
            timestamp=submitted_at,
            status=ReviewStatus.PENDING_MANAGER_REVIEW,
            rationale="Submitted from the browser portal review screen.",
        ),
    )
    return ReviewRequest(
        review_id=uuid4().hex[:12],
        draft_id=draft_id,
        trip_plan=plan,
        policy_snapshot=policy_snapshot.model_copy(deep=True),
        policy_result=policy_result.model_copy(deep=True),
        status=ReviewStatus.PENDING_MANAGER_REVIEW,
        submitted_at=submitted_at,
        updated_at=submitted_at,
        history=history,
    )


def apply_review_action(
    review: ReviewRequest,
    *,
    action: ReviewAction,
    actor_id: str,
    rationale: str,
) -> ReviewRequest:
    """Apply a manager decision and return the updated review request."""

    rationale_text = rationale.strip()
    if not rationale_text:
        raise ValueError("Manager review decisions require rationale text.")

    updated_plan = review.trip_plan.model_copy(deep=True)
    if action == ReviewAction.APPROVE:
        outcome = ApprovalOutcome.APPROVED
        next_status = ReviewStatus.APPROVED
    elif action == ReviewAction.REJECT:
        outcome = ApprovalOutcome.REJECTED
        next_status = ReviewStatus.REJECTED
    else:
        outcome = ApprovalOutcome.FLAGGED
        next_status = ReviewStatus.CHANGES_REQUESTED

    updated_plan.record_approval_decision(
        approver_id=actor_id,
        level="manager",
        outcome=outcome,
        justification=rationale_text,
    )
    event_time = _now()
    updated_history = review.history + (
        ReviewHistoryEvent(
            event_type=action.value,
            actor_id=actor_id,
            timestamp=event_time,
            status=next_status,
            rationale=rationale_text,
        ),
    )
    return ReviewRequest(
        review_id=review.review_id,
        draft_id=review.draft_id,
        trip_plan=updated_plan,
        policy_snapshot=review.policy_snapshot.model_copy(deep=True),
        policy_result=review.policy_result.model_copy(deep=True),
        status=next_status,
        submitted_at=review.submitted_at,
        updated_at=event_time,
        history=updated_history,
    )


@dataclass
class ReviewWorkflowStore:
    """In-memory persistence for manager review queue and decision history."""

    reviews_by_id: dict[str, ReviewRequest] = field(default_factory=dict)
    review_ids_by_draft_id: dict[str, str] = field(default_factory=dict)

    @staticmethod
    def _copy_review(review: ReviewRequest) -> ReviewRequest:
        return ReviewRequest(
            review_id=review.review_id,
            draft_id=review.draft_id,
            trip_plan=review.trip_plan.model_copy(deep=True),
            policy_snapshot=review.policy_snapshot.model_copy(deep=True),
            policy_result=review.policy_result.model_copy(deep=True),
            status=review.status,
            submitted_at=review.submitted_at,
            updated_at=review.updated_at,
            history=tuple(review.history),
        )

    def create_or_get(
        self,
        *,
        draft_id: str,
        trip_plan: TripPlan,
        policy_snapshot: PlannerPolicySnapshot,
        policy_result: PolicyCheckResult,
    ) -> ReviewRequest:
        review_id = self.review_ids_by_draft_id.get(draft_id)
        if review_id is not None:
            review = self.reviews_by_id.get(review_id)
            if review is not None:
                return self._copy_review(review)
        review = create_review_request(
            draft_id=draft_id,
            trip_plan=trip_plan,
            policy_snapshot=policy_snapshot,
            policy_result=policy_result,
        )
        self.reviews_by_id[review.review_id] = review
        self.review_ids_by_draft_id[draft_id] = review.review_id
        return self._copy_review(review)

    def list_reviews(self) -> list[ReviewRequest]:
        return sorted(
            (self._copy_review(review) for review in self.reviews_by_id.values()),
            key=lambda review: (review.updated_at, review.submitted_at),
            reverse=True,
        )

    def lookup(self, review_id: str) -> ReviewRequest | None:
        review = self.reviews_by_id.get(review_id)
        if review is None:
            return None
        return self._copy_review(review)

    def lookup_by_draft(self, draft_id: str) -> ReviewRequest | None:
        review_id = self.review_ids_by_draft_id.get(draft_id)
        if review_id is None:
            return None
        return self.lookup(review_id)

    def apply_action(
        self,
        review_id: str,
        *,
        action: ReviewAction,
        actor_id: str,
        rationale: str,
    ) -> ReviewRequest:
        review = self.reviews_by_id.get(review_id)
        if review is None:
            raise KeyError(f"No manager review found for '{review_id}'.")
        updated = apply_review_action(
            review,
            action=action,
            actor_id=actor_id,
            rationale=rationale,
        )
        self.reviews_by_id[review_id] = updated
        return self._copy_review(updated)
