"""Tests for core models."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from travel_plan_permission.models import (
    ApprovalOutcome,
    ExpenseCategory,
    ExpenseItem,
    ExpenseReport,
    TripPlan,
    TripStatus,
)


class TestTripPlan:
    """Tests for TripPlan model."""

    def test_create_trip_plan(self) -> None:
        """Test creating a basic trip plan."""
        plan = TripPlan(
            trip_id="TRIP-001",
            traveler_name="John Doe",
            destination="New York, NY",
            departure_date=date(2025, 1, 15),
            return_date=date(2025, 1, 18),
            purpose="Client meeting",
            estimated_cost=Decimal("1500.00"),
        )

        assert plan.trip_id == "TRIP-001"
        assert plan.traveler_name == "John Doe"
        assert plan.status == TripStatus.DRAFT

    def test_trip_duration_days(self) -> None:
        """Test calculating trip duration."""
        plan = TripPlan(
            trip_id="TRIP-002",
            traveler_name="Jane Smith",
            destination="Chicago, IL",
            departure_date=date(2025, 2, 1),
            return_date=date(2025, 2, 3),
            purpose="Conference",
            estimated_cost=Decimal("2000.00"),
        )

        assert plan.duration_days() == 3

    def test_trip_plan_optional_fields(self) -> None:
        """Trip plan accepts optional orchestration fields."""
        plan = TripPlan(
            trip_id="TRIP-002B",
            traveler_name="Jane Smith",
            traveler_role="Engineer",
            destination="Chicago, IL",
            origin_city="Seattle, WA",
            destination_city="Chicago, IL",
            departure_date=date(2025, 2, 1),
            return_date=date(2025, 2, 3),
            purpose="Conference",
            transportation_mode="air",
            expected_costs={"airfare": Decimal("300.00")},
            funding_source="R&D budget",
            estimated_cost=Decimal("2000.00"),
        )

        payload = plan.model_dump()
        assert payload["traveler_role"] == "Engineer"
        assert payload["origin_city"] == "Seattle, WA"
        assert payload["destination_city"] == "Chicago, IL"
        assert payload["transportation_mode"] == "air"
        assert payload["expected_costs"]["airfare"] == Decimal("300.00")
        assert payload["funding_source"] == "R&D budget"

    def test_trip_single_day(self) -> None:
        """Test single-day trip duration."""
        plan = TripPlan(
            trip_id="TRIP-003",
            traveler_name="Bob Wilson",
            destination="Boston, MA",
            departure_date=date(2025, 3, 10),
            return_date=date(2025, 3, 10),
            purpose="Day trip meeting",
            estimated_cost=Decimal("500.00"),
        )

        assert plan.duration_days() == 1

    def test_record_approval_history(self) -> None:
        """Trip plan records immutable approval history."""
        plan = TripPlan(
            trip_id="TRIP-004",
            traveler_name="Alice Manager",
            destination="Austin, TX",
            departure_date=date(2025, 4, 1),
            return_date=date(2025, 4, 3),
            purpose="Sales pitch",
            estimated_cost=Decimal("900.00"),
        )

        event = plan.record_approval_decision(
            approver_id="mgr-123",
            level="manager",
            outcome=ApprovalOutcome.APPROVED,
            justification="Budget within limits",
            timestamp=datetime(2025, 3, 1, tzinfo=UTC),
        )

        assert plan.status == TripStatus.APPROVED
        assert event.previous_status == TripStatus.DRAFT
        assert len(plan.approval_history) == 1
        assert plan.approval_history[0].new_status == TripStatus.APPROVED

        with pytest.raises(ValueError):
            plan.record_approval_decision(
                approver_id="board-1",
                level="board",
                outcome=ApprovalOutcome.OVERRIDDEN,
            )

        assert not hasattr(plan.approval_history, "append")


class TestExpenseReport:
    """Tests for ExpenseReport model."""

    def test_create_expense_report(self) -> None:
        """Test creating an expense report."""
        report = ExpenseReport(
            report_id="EXP-001",
            trip_id="TRIP-001",
            traveler_name="John Doe",
        )

        assert report.report_id == "EXP-001"
        assert report.expenses == []
        assert report.total_amount() == Decimal("0")

    def test_expense_report_total(self) -> None:
        """Test calculating total expenses."""
        report = ExpenseReport(
            report_id="EXP-002",
            trip_id="TRIP-001",
            traveler_name="John Doe",
            expenses=[
                ExpenseItem(
                    category=ExpenseCategory.AIRFARE,
                    description="Round trip flight",
                    amount=Decimal("450.00"),
                    expense_date=date(2025, 1, 15),
                ),
                ExpenseItem(
                    category=ExpenseCategory.LODGING,
                    description="Hotel - 3 nights",
                    amount=Decimal("600.00"),
                    expense_date=date(2025, 1, 15),
                ),
                ExpenseItem(
                    category=ExpenseCategory.MEALS,
                    description="Dinner with client",
                    amount=Decimal("85.50"),
                    expense_date=date(2025, 1, 16),
                ),
            ],
        )

        assert report.total_amount() == Decimal("1135.50")

    def test_expenses_by_category(self) -> None:
        """Test grouping expenses by category."""
        report = ExpenseReport(
            report_id="EXP-003",
            trip_id="TRIP-002",
            traveler_name="Jane Smith",
            expenses=[
                ExpenseItem(
                    category=ExpenseCategory.MEALS,
                    description="Breakfast",
                    amount=Decimal("25.00"),
                    expense_date=date(2025, 2, 1),
                ),
                ExpenseItem(
                    category=ExpenseCategory.MEALS,
                    description="Lunch",
                    amount=Decimal("35.00"),
                    expense_date=date(2025, 2, 1),
                ),
                ExpenseItem(
                    category=ExpenseCategory.GROUND_TRANSPORT,
                    description="Taxi to airport",
                    amount=Decimal("50.00"),
                    expense_date=date(2025, 2, 1),
                ),
            ],
        )

        by_category = report.expenses_by_category()

        assert by_category[ExpenseCategory.MEALS] == Decimal("60.00")
        assert by_category[ExpenseCategory.GROUND_TRANSPORT] == Decimal("50.00")
        assert ExpenseCategory.AIRFARE not in by_category


class TestExpenseItem:
    """Tests for ExpenseItem model."""

    def test_expense_item_with_receipt(self) -> None:
        """Test expense item with receipt attached."""
        item = ExpenseItem(
            category=ExpenseCategory.LODGING,
            description="Hotel stay",
            amount=Decimal("200.00"),
            expense_date=date(2025, 1, 15),
            receipt_attached=True,
        )

        assert item.receipt_attached is True

    def test_expense_item_default_no_receipt(self) -> None:
        """Test expense item defaults to no receipt."""
        item = ExpenseItem(
            category=ExpenseCategory.MEALS,
            description="Coffee",
            amount=Decimal("5.00"),
            expense_date=date(2025, 1, 15),
        )

        assert item.receipt_attached is False

    def test_expense_amount_must_be_non_negative(self) -> None:
        """Test that expense amount cannot be negative."""
        with pytest.raises(ValueError):
            ExpenseItem(
                category=ExpenseCategory.OTHER,
                description="Invalid",
                amount=Decimal("-10.00"),
                expense_date=date(2025, 1, 15),
            )
