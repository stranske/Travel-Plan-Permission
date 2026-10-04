from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

import travel_plan_permission.policy_lite as policy_lite
from travel_plan_permission import PolicyContext, TripPlan
from travel_plan_permission.policy import (
    AdvanceBookingRule,
    CabinClassRule,
    FareComparisonRule,
    LocalOvernightRule,
    NonReimbursableRule,
    PolicyEngine,
    RuleOutcome,
    Severity,
)


@pytest.mark.parametrize(
    "field",
    [
        "flight_duration_hours",
        "distance_from_office_miles",
        "driving_cost",
        "flight_cost",
        "selected_fare",
        "lowest_fare",
    ],
)
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), -1])
def test_blocking_rules_fail_closed_on_absent_or_nonfinite_input(
    field: str, value: float | int
) -> None:
    """Keep the source #1429 boundary and omitted-input acceptance gate runnable."""

    payload = {
        "trip_id": "fail-closed-acceptance",
        "traveler_name": "Acceptance Traveler",
        "destination": "Chicago, IL",
        "departure_date": date(2026, 10, 10),
        "return_date": date(2026, 10, 12),
        "purpose": "Acceptance audit",
        "estimated_cost": Decimal("100"),
        field: value,
    }
    with pytest.raises(ValidationError) as exc_info:
        TripPlan.model_validate(payload)
    assert any(error["loc"] == (field,) for error in exc_info.value.errors())

    missing_fare = FareComparisonRule(Decimal("200"), Severity.BLOCKING).evaluate(
        PolicyContext(selected_fare=Decimal("100"))
    )
    missing_duration = CabinClassRule(5, ["economy"], Severity.BLOCKING).evaluate(
        PolicyContext(cabin_class="business", selected_fare=Decimal("100"))
    )
    missing_expenses = NonReimbursableRule(["alcohol"], Severity.BLOCKING).evaluate(
        PolicyContext(expenses=None)
    )
    for result in (missing_fare, missing_duration, missing_expenses):
        assert result.severity == Severity.BLOCKING
        assert result.passed is False
        assert result.outcome in {RuleOutcome.FAILED, RuleOutcome.MISSING_DATA}


def test_policy_lite_reports_missing_inputs() -> None:
    context = PolicyContext(
        departure_date=date(2024, 9, 15),
        overnight_stay=True,
        meal_per_diem_requested=True,
    )

    engine = PolicyEngine(
        [
            AdvanceBookingRule(7, Severity.BLOCKING),
            FareComparisonRule(Decimal("200"), Severity.BLOCKING),
            LocalOvernightRule(50, Severity.BLOCKING),
        ]
    )
    diagnostics = policy_lite.diagnose_missing_inputs(context, engine)

    by_rule = {diag.rule_id: diag for diag in diagnostics}
    assert by_rule["advance_booking"].missing_fields == ["booking_date"]
    assert "fare_comparison" in by_rule
    assert by_rule["fare_comparison"].missing_fields == ["selected_fare", "lowest_fare"]
    assert "missing required inputs" in by_rule["fare_comparison"].message.lower()
    assert "selected_fare" in by_rule["fare_comparison"].message
    assert "lowest_fare" in by_rule["fare_comparison"].message
    assert "local_overnight" in by_rule
    assert by_rule["local_overnight"].missing_fields == ["distance_from_office_miles"]
    assert "distance_from_office_miles" in by_rule["local_overnight"].message
    results = {result.rule_id: result for result in engine.validate(context)}
    for rule_id in ("advance_booking", "local_overnight"):
        assert results[rule_id].outcome == RuleOutcome.MISSING_DATA
        assert results[rule_id].passed is False
        assert results[rule_id].severity == Severity.BLOCKING


@pytest.mark.parametrize("severity", [Severity.BLOCKING, Severity.ADVISORY, Severity.INFO])
@pytest.mark.parametrize("rule_id", ["advance_booking", "local_overnight"])
def test_policy_lite_matches_severity_dependent_missing_data(rule_id: str, severity: str) -> None:
    rule = (
        AdvanceBookingRule(7, severity)
        if rule_id == "advance_booking"
        else LocalOvernightRule(50, severity)
    )
    engine = PolicyEngine([rule])
    context = PolicyContext(departure_date=date(2024, 9, 15), overnight_stay=True)

    result = engine.validate(context)[0]
    diagnostics = policy_lite.diagnose_missing_inputs(context, engine)

    if severity == Severity.BLOCKING:
        assert result.outcome == RuleOutcome.MISSING_DATA
        assert result.passed is False
        assert [diag.rule_id for diag in diagnostics] == [rule_id]
    else:
        assert result.outcome == RuleOutcome.SKIPPED
        assert result.passed is True
        assert diagnostics == []


def test_policy_lite_omits_passed_and_inapplicable_missing_fields() -> None:
    engine = PolicyEngine.from_file()
    context = PolicyContext()
    results = {result.rule_id: result for result in engine.validate(context)}

    diagnostics = policy_lite.diagnose_missing_inputs(context, engine)
    rule_ids = {diag.rule_id for diag in diagnostics}

    assert "fare_comparison" in rule_ids
    for rule_id in (
        "cabin_class",
        "driving_vs_flying",
        "local_overnight",
        "meal_per_diem",
        "third_party_paid",
    ):
        assert results[rule_id].passed is True
        assert rule_id not in rule_ids


def test_policy_lite_skips_local_overnight_when_not_overnight() -> None:
    context = PolicyContext(overnight_stay=False)

    diagnostics = policy_lite.diagnose_missing_inputs(context)

    rule_ids = {diag.rule_id for diag in diagnostics}
    assert "local_overnight" not in rule_ids


@pytest.mark.parametrize(
    ("rule_id", "context_kwargs", "expected_outcome", "expected_passed"),
    [
        (
            "third_party_paid",
            {"third_party_payments": None},
            RuleOutcome.SKIPPED,
            True,
        ),
        (
            "third_party_paid",
            {"third_party_payments": []},
            RuleOutcome.SKIPPED,
            True,
        ),
        (
            "cabin_class",
            {"overnight_stay": True, "distance_from_office_miles": 60.0},
            RuleOutcome.SKIPPED,
            True,
        ),
        (
            "cabin_class",
            {
                "cabin_class": None,
                "flight_duration_hours": 4.0,
                "selected_fare": Decimal("300"),
            },
            RuleOutcome.MISSING_DATA,
            False,
        ),
    ],
)
def test_four_state_outcomes_distinguish_skipped_from_missing_data(
    rule_id: str,
    context_kwargs: dict[str, object],
    expected_outcome: str,
    expected_passed: bool,
) -> None:
    engine = PolicyEngine.from_yaml(f"""
rules:
  {rule_id}:
    severity: blocking
""")
    context = PolicyContext(**context_kwargs)
    results = {result.rule_id: result for result in engine.validate(context)}

    result = results[rule_id]
    assert result.outcome == expected_outcome
    assert result.passed is expected_passed
    diagnostics = policy_lite.diagnose_missing_inputs(context, engine)
    rule_ids = {diag.rule_id for diag in diagnostics}
    assert (rule_id in rule_ids) is (expected_outcome == RuleOutcome.MISSING_DATA)
    if expected_outcome == RuleOutcome.MISSING_DATA:
        assert result.severity == Severity.BLOCKING
