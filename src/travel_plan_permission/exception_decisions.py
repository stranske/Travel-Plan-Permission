"""HTTP boundary for authorized portal exception decisions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi import HTTPException, status

from .exception_authority import authorize_exception_tier
from .models import InvalidExceptionTransition
from .planner_auth import PlannerAuthContext
from .security import AuditEventType

if TYPE_CHECKING:
    from .http_service import PlannerProposalStore


def apply_overdue_escalations(
    proposal_store: PlannerProposalStore,
    draft_id: str,
    stored: list,
    *,
    now: datetime | None = None,
) -> bool:
    """Mutate stored exception requests in place and record routing audit events."""

    reference_time = now or datetime.now(UTC)
    changed = False
    for index, request in enumerate(stored):
        previous_level = request.approval_level
        if not request.escalate_if_overdue(reference_time=reference_time):
            continue
        changed = True
        if request.approval_level == previous_level:
            continue
        proposal_store.security.audit_log.record(
            event_type=AuditEventType.EXCEPTION,
            actor="sla-escalation",
            subject=draft_id,
            outcome="escalated",
            metadata={
                "exception_index": index,
                "previous_level": (previous_level.value if previous_level is not None else None),
                "approval_level": (
                    request.approval_level.value if request.approval_level is not None else None
                ),
            },
        )
    return changed


def escalate_draft_exceptions(
    proposal_store: PlannerProposalStore,
    draft_id: str,
    *,
    persist: bool = True,
) -> bool:
    """Apply the existing SLA to every draft request and persist changed routing."""

    stored = proposal_store.exception_requests_by_draft_id.get(draft_id)
    if not stored:
        return False
    snapshot = [request.model_copy(deep=True) for request in stored]
    if not apply_overdue_escalations(proposal_store, draft_id, stored):
        return False
    if not persist:
        return True
    try:
        proposal_store._persist_state()
    except Exception:
        stored[:] = snapshot
        raise
    return True


def decide_portal_exception(
    proposal_store: PlannerProposalStore,
    draft_id: str,
    *,
    exception_index: int,
    auth_context: PlannerAuthContext,
    approved: bool,
    notes: str | None,
) -> None:
    """Authorize the routed tier and translate missing or finalized decisions."""

    # Refresh once before authorization; never raise the tier after it succeeds.
    proposal_store.escalate_exception_requests(draft_id)
    try:
        pending = proposal_store.lookup_exception_request(
            draft_id,
            exception_index=exception_index,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Exception request not found.",
        ) from exc
    authorize_exception_tier(
        auth_context,
        pending,
        security=proposal_store.security,
        persist_audit=proposal_store.persist_audit_events,
        draft_id=draft_id,
        exception_index=exception_index,
    )
    try:
        proposal_store.decide_exception_request(
            draft_id,
            exception_index=exception_index,
            actor_id=auth_context.subject,
            approved=approved,
            notes=notes,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Exception request not found.",
        ) from exc
    except InvalidExceptionTransition as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
