from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

import travel_plan_permission.policy_lite as policy_lite
from travel_plan_permission import PolicyContext, PolicyEngine, Severity, TripPlan


def test_policy_lite_reports_missing_inputs() -> None:
    context = PolicyContext(
        booking_date=date(2024, 8, 1),
        departure_date=date(2024, 9, 15),
        overnight_stay=True,
        meal_per_diem_requested=True,
    )

    diagnostics = policy_lite.diagnose_missing_inputs(context)

    by_rule = {diag.rule_id: diag for diag in diagnostics}
    assert "fare_comparison" in by_rule
    assert by_rule["fare_comparison"].missing_fields == ["selected_fare", "lowest_fare"]
    assert "missing required inputs" in by_rule["fare_comparison"].message.lower()
    assert "selected_fare" in by_rule["fare_comparison"].message
    assert "lowest_fare" in by_rule["fare_comparison"].message
    assert "local_overnight" in by_rule
    assert by_rule["local_overnight"].missing_fields == ["distance_from_office_miles"]
    assert "distance_from_office_miles" in by_rule["local_overnight"].message


def test_policy_lite_skips_local_overnight_when_not_overnight() -> None:
    context = PolicyContext(overnight_stay=False)

    diagnostics = policy_lite.diagnose_missing_inputs(context)

    rule_ids = {diag.rule_id for diag in diagnostics}
    assert "local_overnight" not in rule_ids


def test_blocking_rules_fail_closed_on_absent_or_nonfinite_input() -> None:
    """Blocking policy controls reject incomplete evidence and invalid HTTP-model values."""

    engine = PolicyEngine.from_file()
    missing_evidence = PolicyContext(
        selected_fare=Decimal("900"),
        cabin_class="business",
        expenses=None,
    )

    results = {result.rule_id: result for result in engine.validate(missing_evidence)}

    assert results["fare_comparison"].passed is False
    assert results["fare_comparison"].severity == Severity.BLOCKING
    assert results["cabin_class"].passed is False
    assert results["cabin_class"].severity == Severity.BLOCKING
    assert results["non_reimbursable"].passed is False
    assert results["non_reimbursable"].severity == Severity.BLOCKING

    base_plan = {
        "trip_id": "TRIP-FINITE-001",
        "traveler_name": "Alex Rivera",
        "destination": "Chicago, IL",
        "departure_date": date(2026, 9, 15),
        "return_date": date(2026, 9, 20),
        "purpose": "Client workshop",
        "estimated_cost": Decimal("1000"),
    }
    invalid_numeric_values = {
        "flight_duration_hours": (float("nan"), float("inf"), float("-inf"), -1.0),
        "distance_from_office_miles": (float("nan"), float("inf"), float("-inf"), -1.0),
        "selected_fare": (Decimal("NaN"), Decimal("Infinity"), Decimal("-1")),
        "lowest_fare": (Decimal("NaN"), Decimal("Infinity"), Decimal("-1")),
        "driving_cost": (Decimal("NaN"), Decimal("Infinity"), Decimal("-1")),
        "flight_cost": (Decimal("NaN"), Decimal("Infinity"), Decimal("-1")),
    }
    for field_name, invalid_values in invalid_numeric_values.items():
        for invalid_value in invalid_values:
            with pytest.raises(ValueError):
                TripPlan(**base_plan, **{field_name: invalid_value})
