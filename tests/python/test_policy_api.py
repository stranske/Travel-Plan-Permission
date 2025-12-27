from datetime import date
from decimal import Decimal

from travel_plan_permission import (
    ExpenseCategory,
    PolicyCheckResult,
    Receipt,
    ReconciliationResult,
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


def test_policy_api_documentation_examples_match_models() -> None:
    trip_plan_payload = {
        "trip_id": "TRIP-1001",
        "traveler_name": "Alex Rivera",
        "traveler_role": "Senior Analyst",
        "department": "Finance",
        "destination": "Chicago, IL 60601",
        "origin_city": "Austin, TX",
        "destination_city": "Chicago, IL",
        "departure_date": "2025-06-10",
        "return_date": "2025-06-12",
        "purpose": "Quarterly planning summit",
        "transportation_mode": "air",
        "expected_costs": {"airfare": 420.50, "lodging": 600.00},
        "funding_source": "FIN-OPS",
        "estimated_cost": 1200.50,
        "status": "submitted",
        "expense_breakdown": {"airfare": 420.50, "lodging": 600.00, "meals": 180.00},
        "selected_providers": {"airfare": "Skyway Air", "lodging": "Lakeside Hotel"},
        "validation_results": [],
        "approval_history": [],
        "exception_requests": [],
    }

    plan = TripPlan.model_validate(trip_plan_payload)
    assert plan.trip_id == "TRIP-1001"

    policy_result_payload = {
        "status": "fail",
        "issues": [
            {
                "code": "advance_booking",
                "message": "Flights must be booked 14 days in advance",
                "severity": "warning",
                "context": {"rule_id": "advance_booking", "severity": "advisory"},
            }
        ],
        "policy_version": "d7a6d25a",
    }

    policy_result = PolicyCheckResult.model_validate(policy_result_payload)
    assert policy_result.status == "fail"
    assert policy_result.issues[0].code == "advance_booking"

    reconciliation_payload = {
        "trip_id": "TRIP-1004",
        "report_id": "TRIP-1004-reconciliation",
        "planned_total": 900.00,
        "actual_total": 325.25,
        "variance": -574.75,
        "status": "under_budget",
        "receipt_count": 2,
        "receipts_by_type": {".pdf": 1, ".png": 1},
        "expenses_by_category": {"other": 325.25},
    }

    reconciliation_result = ReconciliationResult.model_validate(reconciliation_payload)
    assert reconciliation_result.receipt_count == 2
    assert reconciliation_result.status == "under_budget"
    assert ExpenseCategory.OTHER in reconciliation_result.expenses_by_category
