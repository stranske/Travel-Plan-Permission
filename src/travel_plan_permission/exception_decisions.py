"""HTTP boundary for authorized portal exception decisions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException, status

from .exception_authority import authorize_exception_tier
from .models import InvalidExceptionTransition
from .planner_auth import PlannerAuthContext

if TYPE_CHECKING:
    from .http_service import PlannerProposalStore


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
