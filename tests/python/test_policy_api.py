from datetime import date
from decimal import Decimal

from travel_plan_permission import (
    ExpenseCategory,
    Receipt,
    TripPlan,
    check_trip_plan,
    list_allowed_vendors,
    reconcile,
)


def _plan(*, destination: str = "New York, NY") -> TripPlan:
    return TripPlan(
        trip_id="TRIP-API-001",
        traveler_name="Alex Rivera",
        destination=destination,
        departure_date=date(2024, 9, 15),
        return_date=date(2024, 9, 20),
        purpose="Client workshop",
        estimated_cost=Decimal("1000.00"),
    )


def test_check_trip_plan_reports_policy_issues() -> None:
    plan = _plan()

    result = check_trip_plan(plan)

    assert result.policy_version
    assert result.status == "fail"
    assert any(issue.code == "fare_evidence" for issue in result.issues)
    for issue in result.issues:
        assert issue.context["rule_id"] == issue.code


def test_list_allowed_vendors_returns_registry_matches() -> None:
    plan = _plan(destination="New York, NY")

    vendors = list_allowed_vendors(plan)

    assert vendors == [
        "Blue Skies Airlines",
        "Citywide Rides",
        "Downtown Suites",
    ]


def test_reconcile_summarizes_receipts() -> None:
    plan = _plan()
    receipts = [
        Receipt(
            total=Decimal("500.00"),
            date=date(2024, 9, 16),
            vendor="Metro Cab",
            file_reference="receipt-001.pdf",
            file_size_bytes=1024,
        ),
        Receipt(
            total=Decimal("700.00"),
            date=date(2024, 9, 17),
            vendor="Hotel Central",
            file_reference="receipt-002.png",
            file_size_bytes=2048,
        ),
    ]

    result = reconcile(plan, receipts)

    assert result.status == "over_budget"
    assert result.receipt_count == 2
    assert result.receipts_by_type == {".pdf": 1, ".png": 1}
    assert result.expenses_by_category == {ExpenseCategory.OTHER: Decimal("1200.00")}
