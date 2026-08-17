from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

import travel_plan_permission.policy_lite as policy_lite
from travel_plan_permission import PolicyContext
from travel_plan_permission.policy import PolicyEngine, RuleOutcome, Severity


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
    engine = PolicyEngine.from_yaml(
        f"""
rules:
  {rule_id}:
    severity: blocking
"""
    )
    context = PolicyContext(**context_kwargs)
    results = {result.rule_id: result for result in engine.validate(context)}

    result = results[rule_id]
    assert result.outcome == expected_outcome
    assert result.passed is expected_passed
    if expected_outcome == RuleOutcome.MISSING_DATA:
        assert result.severity == Severity.BLOCKING
