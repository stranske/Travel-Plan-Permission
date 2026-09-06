"""Authority checks that bind routed exception tiers to authenticated subjects.

Routing an exception request to the director or board tier is only meaningful if
deciding it actually requires that authority. These helpers live outside
``http_service`` so the enforcement contract stays readable and testable
independently of the portal's request plumbing.
"""

from __future__ import annotations

from fastapi import HTTPException, status

from .models import (
    ExceptionApprovalLevel,
    ExceptionRequest,
    determine_exception_approval_level,
)
from .planner_auth import PlannerAuthContext
from .security import (
    AuditEventType,
    ExceptionTierEntitlementError,
    ExceptionTierEntitlements,
    SecurityModel,
    exception_tier_rank,
)

__all__ = [
    "authorize_exception_tier",
    "routed_exception_level",
]


def routed_exception_level(exception: ExceptionRequest) -> ExceptionApprovalLevel:
    """Return the level an exception is currently routed at.

    The stored ``approval_level`` carries any 48-hour escalation, while
    ``determine_exception_approval_level`` re-derives the level the request's own
    type and amount demand. Take the higher of the two so a stale or under-stated
    stored level can never lower the authority required to decide the request.
    """

    derived = determine_exception_approval_level(exception.type, exception.amount)
    stored = exception.approval_level
    if stored is None:
        return derived
    return max(stored, derived, key=exception_tier_rank)


def _load_entitlements() -> ExceptionTierEntitlements:
    try:
        return ExceptionTierEntitlements.from_env()
    except ExceptionTierEntitlementError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


def authorize_exception_tier(
    auth_context: PlannerAuthContext,
    exception: ExceptionRequest,
    *,
    security: SecurityModel,
    draft_id: str,
    exception_index: int,
) -> ExceptionApprovalLevel:
    """Fail closed unless the authenticated subject is entitled to this tier.

    Generic ``Permission.APPROVE`` — already checked by the route — covers the
    baseline tier only. Director and board routing require an explicit
    entitlement bound to ``auth_context.subject``; request-supplied fields such
    as ``actor_role`` or a posted ``actor_id`` are never consulted.
    """

    required_level = routed_exception_level(exception)
    entitlements = _load_entitlements()
    if entitlements.permits(auth_context.subject, required_level):
        return required_level

    granted = entitlements.highest_tier(auth_context.subject)
    security.audit_log.record(
        event_type=AuditEventType.EXCEPTION,
        actor=auth_context.subject,
        subject=draft_id,
        outcome="denied",
        metadata={
            "exception_type": exception.type.value,
            "exception_index": exception_index,
            "required_level": required_level.value,
            "granted_level": granted.value if granted is not None else None,
            "reason": "insufficient_exception_tier_entitlement",
        },
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            f"Subject is not entitled to decide a '{required_level.value}'-level exception request."
        ),
    )
