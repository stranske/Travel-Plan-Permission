"""Serialize the planner's persisted snapshot without owning its lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def serialize_planner_state(
    store: Any,
    serialize_draft: Callable[[Any], Any],
    serialize_audit_event: Callable[[Any], Any],
) -> dict[str, object]:
    return {
        "plans_by_trip_id": {
            trip_id: trip_plan.model_dump(mode="json")
            for trip_id, trip_plan in store.plans_by_trip_id.items()
        },
        "proposals_by_execution_id": {
            execution_id: {
                "trip_plan": stored.trip_plan.model_dump(mode="json"),
                "request": stored.request.model_dump(mode="json"),
                "response": stored.response.model_dump(mode="json"),
            }
            for execution_id, stored in store.proposals_by_execution_id.items()
        },
        "portal_drafts_by_id": {
            draft_id: serialize_draft(draft)
            for draft_id, draft in store.portal_drafts_by_id.items()
        },
        "expense_drafts_by_id": {
            draft_id: serialize_draft(draft)
            for draft_id, draft in store.expense_drafts_by_id.items()
        },
        "manager_reviews": {
            review_id: {
                "draft_id": review.draft_id,
                "trip_plan": review.trip_plan.model_dump(mode="json"),
                "policy_snapshot": review.policy_snapshot.model_dump(mode="json"),
                "policy_result": review.policy_result.model_dump(mode="json"),
                "status": review.status.value,
                "submitted_at": review.submitted_at.isoformat(),
                "updated_at": review.updated_at.isoformat(),
                "history": [
                    {
                        "event_type": event.event_type,
                        "actor_id": event.actor_id,
                        "timestamp": event.timestamp.isoformat(),
                        "status": event.status.value,
                        "rationale": event.rationale,
                    }
                    for event in review.history
                ],
            }
            for review_id, review in store.manager_reviews.reviews_by_id.items()
        },
        "review_ids_by_draft_id": dict(store.manager_reviews.review_ids_by_draft_id),
        "exception_requests_by_draft_id": {
            draft_id: [request.model_dump(mode="json") for request in requests]
            for draft_id, requests in store.exception_requests_by_draft_id.items()
        },
        "audit_events": [serialize_audit_event(event) for event in store.security.audit_log.events],
        "pending_audit_events": [event.as_row() for event in store.pending_audit_events],
    }
