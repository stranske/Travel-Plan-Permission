"""Tests for trip plan validation rules."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from travel_plan_permission.models import ExpenseCategory, TripPlan
from travel_plan_permission.validation import (
    AdvanceBookingRule,
    BudgetLimitRule,
    DurationLimitRule,
    PolicyValidator,
    ValidationResult,
    ValidationSeverity,
)


def _build_plan(
    *,
    departure: date,
    return_date: date,
    destination: str = "Chicago, IL",
    estimated_cost: Decimal = Decimal("1000"),
    expense_breakdown: dict[ExpenseCategory, Decimal] | None = None,
) -> TripPlan:
    return TripPlan(
        trip_id="TRIP-100",
        traveler_name="Alex Doe",
        destination=destination,
        departure_date=departure,
        return_date=return_date,
        purpose="Conference",
        estimated_cost=estimated_cost,
        expense_breakdown=expense_breakdown or {},
    )


class TestAdvanceBookingRule:
    """Advance booking rule behavior."""

    def test_blocks_when_notice_too_short(self) -> None:
        rule = AdvanceBookingRule(
            name="advance_domestic",
            code="ADV-DOM",
            min_days_domestic=7,
            min_days_international=14,
            international_destinations=["paris"],
        )
        plan = _build_plan(
            departure=date(2025, 5, 5),
            return_date=date(2025, 5, 10),
            destination="New York, NY",
        )

        results = rule.evaluate(plan, reference_date=date(2025, 5, 1))

        assert results == [
            ValidationResult(
                code="ADV-DOM",
                message="Trips must be booked at least 7 days in advance; only 4 days provided",
                severity=ValidationSeverity.ERROR,
                rule_name="advance_domestic",
                blocking=True,
            )
        ]

    def test_international_notice_uses_international_threshold(self) -> None:
        rule = AdvanceBookingRule(
            name="advance_international",
            code="ADV-INTL",
            min_days_domestic=7,
            min_days_international=14,
            international_destinations=["paris"],
        )
        plan = _build_plan(
            departure=date(2025, 5, 20),
            return_date=date(2025, 5, 26),
            destination="Paris, France",
        )

        results = rule.evaluate(plan, reference_date=date(2025, 5, 10))

        assert results and results[0].message.startswith(
            "Trips must be booked at least 14"
        )

    def test_passes_when_notice_is_sufficient(self) -> None:
        rule = AdvanceBookingRule(
            name="advance_ok",
            code="ADV-OK",
            min_days_domestic=7,
            international_destinations=["london"],
        )
        plan = _build_plan(
            departure=date(2025, 6, 1),
            return_date=date(2025, 6, 5),
            destination="Chicago, IL",
        )

        results = rule.evaluate(plan, reference_date=date(2025, 5, 20))

        assert results == []


class TestBudgetLimitRule:
    """Budget limit rule behavior."""

    def test_trip_and_category_limits(self) -> None:
        rule = BudgetLimitRule(
            name="budget_rule",
            code="BUD-001",
            trip_limit=Decimal("1500"),
            category_limits={"lodging": Decimal("500"), "meals": Decimal("200")},
        )
        plan = _build_plan(
            departure=date(2025, 4, 1),
            return_date=date(2025, 4, 3),
            estimated_cost=Decimal("1800"),
            expense_breakdown={
                ExpenseCategory.LODGING: Decimal("650"),
                ExpenseCategory.MEALS: Decimal("220"),
            },
        )

        results = rule.evaluate(plan)

        messages = {result.message for result in results}
        assert len(results) == 3
        assert "Estimated cost 1800 exceeds trip limit 1500" in messages
        assert "Planned lodging spend 650 exceeds limit 500" in messages
        assert "Planned meals spend 220 exceeds limit 200" in messages

    def test_passes_when_within_limits(self) -> None:
        rule = BudgetLimitRule(
            name="budget_ok",
            code="BUD-OK",
            trip_limit=Decimal("2000"),
            category_limits={"lodging": Decimal("800")},
        )
        plan = _build_plan(
            departure=date(2025, 4, 10),
            return_date=date(2025, 4, 12),
            estimated_cost=Decimal("1500"),
            expense_breakdown={ExpenseCategory.LODGING: Decimal("600")},
        )

        assert rule.evaluate(plan) == []


class TestDurationLimitRule:
    """Duration limit rule behavior."""

    def test_blocks_when_duration_exceeds_max(self) -> None:
        rule = DurationLimitRule(
            name="duration_limit",
            code="DUR-001",
            max_consecutive_days=5,
        )
        plan = _build_plan(
            departure=date(2025, 3, 1),
            return_date=date(2025, 3, 8),
        )

        results = rule.evaluate(plan)

        assert results == [
            ValidationResult(
                code="DUR-001",
                message="Trip duration 8 days exceeds maximum of 5",
                severity=ValidationSeverity.ERROR,
                rule_name="duration_limit",
                blocking=True,
            )
        ]

    def test_allows_duration_within_limit(self) -> None:
        rule = DurationLimitRule(
            name="duration_limit",
            code="DUR-001",
            max_consecutive_days=10,
        )
        plan = _build_plan(
            departure=date(2025, 3, 1),
            return_date=date(2025, 3, 5),
        )

        assert rule.evaluate(plan) == []


class TestPolicyValidator:
    """End-to-end validation integration tests."""

    def test_validate_plan_runs_all_rules(self) -> None:
        rules = [
            AdvanceBookingRule(
                name="advance",
                code="ADV",
                min_days_domestic=5,
                min_days_international=14,
                international_destinations=["berlin"],
            ),
            DurationLimitRule(name="duration", code="DUR", max_consecutive_days=10),
        ]
        plan = _build_plan(
            departure=date(2025, 7, 10),
            return_date=date(2025, 7, 25),
            destination="Berlin, Germany",
        )
        validator = PolicyValidator(rules)

        results = validator.validate_plan(plan, reference_date=date(2025, 7, 1))

        codes = {result.code for result in results}
        assert codes == {"ADV", "DUR"}
        assert not validator.can_submit(plan, reference_date=date(2025, 7, 1))

    def test_trip_plan_validate_updates_results(self) -> None:
        rule = DurationLimitRule(name="duration", code="DUR", max_consecutive_days=3)
        validator = PolicyValidator([rule])
        plan = _build_plan(
            departure=date(2025, 8, 1),
            return_date=date(2025, 8, 5),
        )

        results = plan.run_validation(validator=validator)

        assert plan.validation_results == results
        assert results[0].is_blocking is True
