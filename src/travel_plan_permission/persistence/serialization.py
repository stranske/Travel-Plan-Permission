"""Serialize the planner's persisted snapshot without owning its lifecycle."""

from __future__ import annotations

import base64
from collections.abc import Callable
from datetime import datetime
from typing import Any

from ..http_contract_models import PortalDraft, PortalReceiptBinding
from ..policy_api import PlannerProposalOperationResponse
from ..portal_review import PortalArtifact


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
        "audit_events": [
            serialize_audit_event(event) for event in store.security.audit_log.events
        ],
        "pending_audit_events": [
            event.as_row() for event in store.pending_audit_events
        ],
    }


def portal_draft_to_state(draft: PortalDraft) -> dict[str, object]:
    return {
        "receipt_binding": (
            draft.receipt_binding.model_dump(mode="json")
            if draft.receipt_binding
            else None
        ),
        "answers": dict(draft.answers),
        "updated_at": draft.updated_at.isoformat(),
        "cached_artifacts": {
            artifact_name: {
                "filename": artifact.filename,
                "content": base64.b64encode(artifact.content).decode("ascii"),
                "media_type": artifact.media_type,
            }
            for artifact_name, artifact in draft.cached_artifacts.items()
        },
        "submission_response": (
            draft.submission_response.model_dump(mode="json")
            if draft.submission_response is not None
            else None
        ),
    }


def portal_draft_from_state(draft_id: str, serialized: dict[str, Any]) -> PortalDraft:
    return PortalDraft(
        draft_id=draft_id,
        receipt_binding=(
            PortalReceiptBinding.model_validate(serialized["receipt_binding"])
            if serialized.get("receipt_binding") is not None
            else None
        ),
        answers=dict(serialized["answers"]),
        updated_at=datetime.fromisoformat(serialized["updated_at"]),
        cached_artifacts={
            artifact_name: PortalArtifact(
                filename=artifact_payload["filename"],
                content=base64.b64decode(artifact_payload["content"]),
                media_type=artifact_payload["media_type"],
            )
            for artifact_name, artifact_payload in serialized.get(
                "cached_artifacts", {}
            ).items()
        },
        submission_response=(
            PlannerProposalOperationResponse.model_validate(
                serialized["submission_response"]
            )
            if serialized.get("submission_response") is not None
            else None
        ),
    )
