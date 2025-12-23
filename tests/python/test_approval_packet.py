"""Tests for approval packet generation."""

from datetime import UTC, date, datetime
from decimal import Decimal

from travel_plan_permission.approval_packet import (
    ApprovalLinks,
    build_approval_packet,
    generate_packet_pdf,
)
from travel_plan_permission.models import (
    ApprovalEvent,
    ApprovalOutcome,
    TripPlan,
    TripStatus,
)


def _sample_trip_plan() -> TripPlan:
    return TripPlan(
        trip_id="TRIP-APPROVAL",
        traveler_name="Casey Traveler",
        destination="Portland, OR",
        departure_date=date(2025, 5, 1),
        return_date=date(2025, 5, 5),
        purpose="Board review meeting",
        estimated_cost=Decimal("1250.50"),
        expense_breakdown={"airfare": Decimal("800.00"), "lodging": Decimal("450.50")},
    )


def _event(index: int) -> ApprovalEvent:
    return ApprovalEvent(
        approver_id=f"approver-{index}",
        level="manager" if index % 2 == 0 else "board",
        outcome=ApprovalOutcome.APPROVED,
        timestamp=datetime(2025, 1, 1, 12, 0, tzinfo=UTC),
        justification="All good",
        previous_status=TripStatus.SUBMITTED,
        new_status=TripStatus.APPROVED,
    )


def test_manager_email_contains_required_fields() -> None:
    """Rendered manager email includes summary, compliance, cost, and decision links."""
    trip = _sample_trip_plan()
    links = ApprovalLinks(
        approve_url="https://example.com/approve",
        reject_url="https://example.com/reject",
        override_url="https://example.com/override",
    )
    packet = build_approval_packet(
        trip_plan=trip,
        compliance_status="Compliant",
        approval_links=links,
        approval_history=[_event(1)],
    )

    body = packet.manager_email.body
    assert "Total cost: $1250.50" in body
    assert "Policy compliance: Compliant" in body
    assert links.approve_url in body
    assert links.reject_url in body
    assert links.override_url in body


def test_pdf_page_counts_scale_with_complexity() -> None:
    """PDF stays single-page for routine trips and grows for complex itineraries."""
    trip = _sample_trip_plan()
    history_single = [_event(1)]
    history_complex = [_event(i) for i in range(25)]

    simple_pdf = generate_packet_pdf(
        trip_plan=trip,
        compliance_status="Compliant",
        cost_breakdown=trip.expense_breakdown,
        approval_history=history_single,
        entries_per_page=20,
    )
    complex_pdf = generate_packet_pdf(
        trip_plan=trip,
        compliance_status="Needs board review",
        cost_breakdown=trip.expense_breakdown,
        approval_history=history_complex,
        entries_per_page=10,
    )

    import re

    simple_pages = len(re.findall(rb"/Type /Page\b", simple_pdf))
    complex_pages = len(re.findall(rb"/Type /Page\b", complex_pdf))

    assert simple_pages == 1
    assert complex_pages >= 2
