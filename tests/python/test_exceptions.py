"""Tests for exception workflow and routing."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from travel_plan_permission.models import (
    ExceptionApprovalLevel,
    ExceptionRequest,
    ExceptionStatus,
    ExceptionType,
    build_exception_dashboard,
    determine_exception_approval_level,
)
from travel_plan_permission.policy import PolicyEngine, Severity


def _justification(text: str = "exception justification text") -> str:
    return (text + " ") * 4


def test_exception_types_cover_advisory_rules() -> None:
    """All advisory policy-lite rules map to an exception type."""

    engine = PolicyEngine.from_file()
    advisory_rules = {
        rule.rule_id for rule in engine.rules if str(rule.severity) == Severity.ADVISORY
    }

    mapped = {ExceptionType.from_policy_rule_id(rule_id).value for rule_id in advisory_rules}

    assert mapped == advisory_rules


def test_exception_request_requires_long_justification() -> None:
    """Exception requests enforce a 50 character justification."""

    with pytest.raises(ValidationError):
        ExceptionRequest(
            type=ExceptionType.ADVANCE_BOOKING,
            justification="too short",
            requestor="traveler-1",
            amount=Decimal("100"),
        )


def test_exception_routing_includes_amount_based_escalation() -> None:
    """Routing escalates based on amount thresholds."""

    manager_level = determine_exception_approval_level(
        ExceptionType.ADVANCE_BOOKING, Decimal("200")
    )
    director_level = determine_exception_approval_level(
        ExceptionType.ADVANCE_BOOKING, Decimal("6000")
    )
    board_level = determine_exception_approval_level(
        ExceptionType.ADVANCE_BOOKING, Decimal("25000")
    )
    local_overnight = determine_exception_approval_level(
        ExceptionType.LOCAL_OVERNIGHT, Decimal("1000")
    )

    assert manager_level == ExceptionApprovalLevel.MANAGER
    assert director_level == ExceptionApprovalLevel.DIRECTOR
    assert board_level == ExceptionApprovalLevel.BOARD
    assert local_overnight == ExceptionApprovalLevel.DIRECTOR


def test_exception_escalates_after_48_hours() -> None:
    """Pending exceptions escalate after the SLA window."""

    submitted = datetime(2024, 1, 1, tzinfo=UTC)
    request = ExceptionRequest(
        type=ExceptionType.MEAL_PER_DIEM,
        justification=_justification(),
        requestor="traveler-2",
        amount=Decimal("100"),
        requested_at=submitted,
    )

    escalated = request.escalate_if_overdue(reference_time=submitted + timedelta(hours=49))

    assert escalated is True
    assert request.status == ExceptionStatus.ESCALATED
    assert request.approval_level == ExceptionApprovalLevel.DIRECTOR
    assert request.escalated_at == submitted + timedelta(hours=49)


def test_exception_dashboard_patterns() -> None:
    """Dashboard aggregates patterns by type, requestor, and approver."""

    request_one = ExceptionRequest(
        type=ExceptionType.ADVANCE_BOOKING,
        justification=_justification("advance booking"),
        requestor="alice",
        amount=Decimal("1500"),
    )
    request_one.approve(approver_id="mgr-1", level=ExceptionApprovalLevel.MANAGER)

    request_two = ExceptionRequest(
        type=ExceptionType.DRIVING_VS_FLYING,
        justification=_justification("driving vs flying"),
        requestor="bob",
        amount=Decimal("7000"),
    )
    request_two.approve(approver_id="director-9", level=ExceptionApprovalLevel.DIRECTOR)

    request_three = ExceptionRequest(
        type=ExceptionType.DRIVING_VS_FLYING,
        justification=_justification("another driving"),
        requestor="alice",
        amount=Decimal("300"),
    )

    dashboard = build_exception_dashboard([request_one, request_two, request_three])

    assert dashboard["by_type"]["advance_booking"] == 1
    assert dashboard["by_type"]["driving_vs_flying"] == 2
    assert dashboard["by_requestor"]["alice"] == 2
    assert dashboard["by_requestor"]["bob"] == 1
    assert dashboard["by_approver"]["mgr-1"] == 1
    assert dashboard["by_approver"]["director-9"] == 1
