import shutil
import subprocess
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from travel_plan_permission import (
    ExpenseCategory,
    PolicyCheckResult,
    PolicyEngine,
    Receipt,
    ReconciliationResult,
    TripPlan,
    check_trip_plan,
    list_allowed_vendors,
    reconcile,
)


@pytest.fixture()
def trip_plan() -> TripPlan:
    return TripPlan(
        trip_id="TRIP-API-001",
        traveler_name="Alex Rivera",
        destination="New York, NY",
        departure_date=date(2024, 9, 15),
        return_date=date(2024, 9, 20),
        purpose="Client workshop",
        estimated_cost=Decimal("1000.00"),
    )


@pytest.fixture()
def over_budget_receipts() -> list[Receipt]:
    return [
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


@pytest.fixture()
def matching_receipts() -> list[Receipt]:
    return [
        Receipt(
            total=Decimal("250.00"),
            date=date(2024, 9, 16),
            vendor="Metro Cab",
            file_reference="receipt-003.pdf",
            file_size_bytes=512,
        ),
        Receipt(
            total=Decimal("750.00"),
            date=date(2024, 9, 18),
            vendor="Hotel Central",
            file_reference="receipt-004.png",
            file_size_bytes=1024,
        ),
    ]


def test_check_trip_plan_reports_policy_issues(trip_plan: TripPlan) -> None:
    result = check_trip_plan(trip_plan)

    assert isinstance(result, PolicyCheckResult)
    assert result.policy_version
    assert result.status == "fail"
    assert any(issue.code == "fare_evidence" for issue in result.issues)
    for issue in result.issues:
        assert issue.context["rule_id"] == issue.code


def test_check_trip_plan_reports_pass_when_no_rules(
    trip_plan: TripPlan, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        PolicyEngine, "from_file", lambda *_args, **_kwargs: PolicyEngine([])
    )

    result = check_trip_plan(trip_plan)

    assert result.status == "pass"
    assert result.issues == []
    assert result.policy_version


def test_check_trip_plan_skips_cost_comparison_when_estimates_missing(
    trip_plan: TripPlan,
) -> None:
    plan = trip_plan.model_copy(update={"expense_breakdown": {}})

    result = check_trip_plan(plan)

    issue_codes = {issue.code for issue in result.issues}
    assert "driving_vs_flying" not in issue_codes
    assert "fare_evidence" in issue_codes


def test_list_allowed_vendors_returns_registry_matches(
    trip_plan: TripPlan,
) -> None:
    vendors = list_allowed_vendors(trip_plan)

    assert isinstance(vendors, list)
    assert vendors == [
        "Blue Skies Airlines",
        "Citywide Rides",
        "Downtown Suites",
    ]


def test_list_allowed_vendors_filters_by_destination_and_date(
    trip_plan: TripPlan,
) -> None:
    plan = trip_plan.model_copy(
        update={"destination": "New York, NY", "departure_date": date(2024, 11, 2)}
    )

    vendors = list_allowed_vendors(plan)

    assert vendors == [
        "Blue Skies Airlines",
        "Downtown Suites",
    ]


def test_list_allowed_vendors_matches_other_destinations(
    trip_plan: TripPlan,
) -> None:
    plan = trip_plan.model_copy(update={"destination": "San Francisco, CA"})

    vendors = list_allowed_vendors(plan)

    assert vendors == [
        "Blue Skies Airlines",
        "Citywide Rides",
    ]


def test_list_allowed_vendors_handles_empty_destination(
    trip_plan: TripPlan,
) -> None:
    plan = trip_plan.model_copy(update={"destination": ""})

    vendors = list_allowed_vendors(plan)

    assert vendors == ["Citywide Rides"]


def test_list_allowed_vendors_handles_no_active_providers(
    trip_plan: TripPlan,
) -> None:
    plan = trip_plan.model_copy(
        update={"departure_date": date(2025, 1, 10), "return_date": date(2025, 1, 12)}
    )

    vendors = list_allowed_vendors(plan)

    assert vendors == []


def test_reconcile_summarizes_receipts(
    trip_plan: TripPlan, over_budget_receipts: list[Receipt]
) -> None:
    result = reconcile(trip_plan, over_budget_receipts)

    assert result.status == "over_budget"
    assert result.receipt_count == 2
    assert result.receipts_by_type == {".pdf": 1, ".png": 1}
    assert result.expenses_by_category == {ExpenseCategory.OTHER: Decimal("1200.00")}


def test_reconcile_matches_estimated_cost(
    trip_plan: TripPlan, matching_receipts: list[Receipt]
) -> None:
    result = reconcile(trip_plan, matching_receipts)

    assert isinstance(result, ReconciliationResult)
    assert result.status == "on_budget"
    assert result.variance == Decimal("0.00")


def test_reconcile_handles_empty_receipts(trip_plan: TripPlan) -> None:
    result = reconcile(trip_plan, [])

    assert result.status == "under_budget"
    assert result.receipt_count == 0
    assert result.receipts_by_type == {}


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


def test_policy_api_markdown_lint() -> None:
    root = Path(__file__).resolve().parents[2]
    local_bin = root / "node_modules" / ".bin" / "markdownlint-cli2"
    lint_bin = local_bin if local_bin.exists() else shutil.which("markdownlint-cli2")
    if not lint_bin:
        pytest.skip("markdownlint-cli2 is not installed")

    subprocess.run(
        [str(lint_bin), "docs/policy-api.md"],
        check=True,
        cwd=root,
    )
