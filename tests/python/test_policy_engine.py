from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from travel_plan_permission import (
    ExpenseCategory,
    ExpenseItem,
    PolicyContext,
    PolicyEngine,
    Severity,
)
from travel_plan_permission.policy import (
    AdvanceBookingRule,
    CabinClassRule,
    LocalOvernightRule,
    RuleOutcome,
)


def test_cabin_class_blocking_rejects_nan_duration() -> None:
    engine = PolicyEngine.from_yaml("""
rules:
  cabin_class:
    severity: blocking
""")
    context = PolicyContext(
        cabin_class="premium",
        flight_duration_hours=float("nan"),
        selected_fare=Decimal("100"),
    )

    result = next(r for r in engine.validate(context) if r.rule_id == "cabin_class")

    assert result.passed is False
    assert result.outcome == RuleOutcome.MISSING_DATA
    assert result.severity == Severity.BLOCKING
    assert "flight_duration_hours" in result.message
    assert result in engine.blocking_results(context)


@pytest.mark.parametrize("duration", [None, float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("cabin", [None, "economy", "premium"])
@pytest.mark.parametrize(
    "severity", [Severity.BLOCKING, Severity.ADVISORY, Severity.INFO]
)
def test_cabin_class_invalid_duration_uses_missing_data_policy(
    duration: float | None, cabin: str | None, severity: str
) -> None:
    rule = CabinClassRule(5, ["economy"], severity)
    context = PolicyContext(
        cabin_class=cabin,
        flight_duration_hours=duration,
        selected_fare=Decimal("100"),
    )

    result = rule.evaluate(context)

    if severity == Severity.BLOCKING:
        assert result.passed is False
        assert result.outcome == RuleOutcome.MISSING_DATA
        assert "flight_duration_hours" in result.message
    else:
        assert result.passed is True
        assert result.outcome == RuleOutcome.SKIPPED


@pytest.mark.parametrize(
    ("cabin", "duration", "passed"),
    [
        ("premium", 4.0, False),
        ("premium", 5.0, False),
        ("premium", 5.1, True),
        ("economy", 4.0, True),
    ],
)
def test_cabin_class_finite_duration_preserves_threshold(
    cabin: str, duration: float, passed: bool
) -> None:
    rule = CabinClassRule(5, ["economy"], Severity.BLOCKING)

    result = rule.evaluate(
        PolicyContext(cabin_class=cabin, flight_duration_hours=duration)
    )

    assert result.passed is passed
    assert result.outcome == (RuleOutcome.PASSED if passed else RuleOutcome.FAILED)


def test_cabin_class_without_flight_remains_inapplicable() -> None:
    result = CabinClassRule(5, ["economy"], Severity.BLOCKING).evaluate(PolicyContext())

    assert result.passed is True
    assert result.outcome == RuleOutcome.SKIPPED


def test_policy_engine_evaluates_all_rules():
    yaml_content = """
rules:
  fare_comparison:
    max_over_lowest: 150
"""
    engine = PolicyEngine.from_yaml(yaml_content)
    context = PolicyContext(
        booking_date=date(2025, 1, 1),
        departure_date=date(2025, 1, 5),
        return_date=date(2025, 1, 7),
        selected_fare=Decimal("600"),
        lowest_fare=Decimal("400"),
        cabin_class="Business",
        flight_duration_hours=2.0,
        fare_evidence_attached=False,
        driving_cost=Decimal("500"),
        flight_cost=Decimal("300"),
        comparable_hotels=[Decimal("150")],
        distance_from_office_miles=10,
        overnight_stay=True,
        meals_provided=True,
        meal_per_diem_requested=True,
        expenses=[
            ExpenseItem(
                category=ExpenseCategory.MEALS,
                description="Liquor with client dinner",
                amount=Decimal("50"),
                expense_date=date(2025, 1, 6),
            )
        ],
        third_party_payments=[{"description": "Sponsor pays hotel", "itemized": False}],
    )

    results = {result.rule_id: result for result in engine.validate(context)}
    assert set(results.keys()) == {
        "fare_comparison",
        "cabin_class",
        "fare_evidence",
        "driving_vs_flying",
        "hotel_comparison",
        "local_overnight",
        "meal_per_diem",
        "non_reimbursable",
        "third_party_paid",
    }

    assert not results["fare_comparison"].passed
    assert not results["cabin_class"].passed
    assert not results["fare_evidence"].passed
    assert not results["driving_vs_flying"].passed
    assert not results["hotel_comparison"].passed
    assert not results["local_overnight"].passed
    assert not results["meal_per_diem"].passed
    assert not results["non_reimbursable"].passed
    assert not results["third_party_paid"].passed

    blocking = engine.blocking_results(context)
    blocking_ids = {result.rule_id for result in blocking}
    assert blocking_ids == {
        "fare_comparison",
        "cabin_class",
        "fare_evidence",
        "non_reimbursable",
        "third_party_paid",
    }
    assert all(result.severity == Severity.BLOCKING for result in blocking)


@pytest.mark.parametrize(
    ("rule", "context"),
    [
        (
            AdvanceBookingRule(days_required=10, severity=Severity.BLOCKING),
            PolicyContext(),
        ),
        (
            AdvanceBookingRule(days_required=10, severity=Severity.BLOCKING),
            PolicyContext(booking_date=date(2025, 1, 1)),
        ),
        (
            AdvanceBookingRule(days_required=10, severity=Severity.BLOCKING),
            PolicyContext(departure_date=date(2025, 1, 11)),
        ),
        (
            LocalOvernightRule(min_distance_miles=50, severity=Severity.BLOCKING),
            PolicyContext(overnight_stay=True),
        ),
    ],
)
def test_blocking_rules_emit_missing_data_not_skipped(rule, context):
    result = rule.evaluate(context)

    assert result.outcome == RuleOutcome.MISSING_DATA
    assert result.passed is False
    assert result.severity == Severity.BLOCKING


@pytest.mark.parametrize(
    ("rule", "context"),
    [
        (
            AdvanceBookingRule(days_required=10, severity=Severity.ADVISORY),
            PolicyContext(booking_date=date(2025, 1, 1)),
        ),
        (
            LocalOvernightRule(min_distance_miles=50, severity=Severity.ADVISORY),
            PolicyContext(overnight_stay=True),
        ),
    ],
)
def test_advisory_rules_skip_missing_data(rule, context):
    result = rule.evaluate(context)

    assert result.outcome == RuleOutcome.SKIPPED
    assert result.passed is True


def test_policy_engine_from_file_defaults():
    engine = PolicyEngine.from_file()
    context = PolicyContext(
        booking_date=date(2025, 1, 1),
        departure_date=date(2025, 1, 20),
        return_date=date(2025, 1, 22),
        selected_fare=Decimal("300"),
        lowest_fare=Decimal("200"),
        cabin_class="Economy",
        flight_duration_hours=4.0,
        fare_evidence_attached=True,
        driving_cost=Decimal("100"),
        flight_cost=Decimal("300"),
        comparable_hotels=[Decimal("120"), Decimal("130")],
        distance_from_office_miles=60,
        overnight_stay=False,
        meals_provided=False,
        meal_per_diem_requested=True,
        expenses=[
            ExpenseItem(
                category=ExpenseCategory.OTHER,
                description="Office supplies for trip",
                amount=Decimal("25"),
                expense_date=date(2025, 1, 3),
            )
        ],
        third_party_payments=[{"description": "Conference lodging", "itemized": True}],
    )

    results = engine.validate(context)
    assert len(results) == 9
    assert all(result.passed for result in results)
    assert engine.blocking_results(context) == []


def test_policy_messages_include_thresholds_from_config():
    engine = PolicyEngine.from_yaml("""
rules:
  fare_comparison:
    max_over_lowest: 175
""")

    context = PolicyContext(
        booking_date=date(2025, 1, 1),
        departure_date=date(2025, 1, 10),
        selected_fare=Decimal("500"),
        lowest_fare=Decimal("300"),
    )

    results = {result.rule_id: result for result in engine.validate(context)}

    # Submission validation remains owned by validation.yaml.
    assert "advance_booking" not in results

    fare = results["fare_comparison"]
    assert not fare.passed
    assert "175" in fare.message


@pytest.mark.parametrize(
    "rule_name", ["fare_comparision", "advance_booking", "unknown", "123"]
)
def test_policy_engine_rejects_unknown_rule_configuration(rule_name: str) -> None:
    with pytest.raises(ValueError, match="policy.yaml: unknown rule") as exc_info:
        PolicyEngine.from_yaml(f"rules:\n  {rule_name}: {{max_over_lowest: 5}}\n")
    assert rule_name in str(exc_info.value)


@pytest.mark.parametrize(
    "rule_name",
    [
        "fare_comparison",
        "cabin_class",
        "fare_evidence",
        "driving_vs_flying",
        "hotel_comparison",
        "local_overnight",
        "meal_per_diem",
        "non_reimbursable",
        "third_party_paid",
    ],
)
@pytest.mark.parametrize("field", ["severty", "123"])
def test_policy_engine_rejects_unknown_rule_fields(rule_name: str, field: str) -> None:
    with pytest.raises(ValueError, match="policy.yaml: unknown field") as exc_info:
        PolicyEngine.from_yaml(f"rules:\n  {rule_name}: {{{field}: blocking}}\n")
    assert f"rules.{rule_name}" in str(exc_info.value)
    assert field in str(exc_info.value)


@pytest.mark.parametrize("content", ["false", "0", "[]", "[blocking]", "blocking"])
def test_policy_engine_rejects_non_mapping_document(
    content: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "policy.yaml"
    path.write_text(content, encoding="utf-8")
    monkeypatch.setenv("TEST_POLICY_YAML", content)
    for load in (
        lambda: PolicyEngine.from_yaml(content),
        lambda: PolicyEngine.from_file(path),
        lambda: PolicyEngine.from_environment("TEST_POLICY_YAML"),
    ):
        with pytest.raises(ValueError, match="policy.yaml: configuration must be a mapping"):
            load()


@pytest.mark.parametrize(
    "value", ["null", "false", "0", "[]", "[severity, blocking]", "blocking"]
)
@pytest.mark.parametrize("level", ["rules", "rule"])
def test_policy_engine_rejects_non_mapping_rules(value: str, level: str) -> None:
    content = (
        f"rules: {value}" if level == "rules" else f"rules:\n  fare_comparison: {value}"
    )
    with pytest.raises(ValueError, match="policy.yaml: rules.*must be a mapping"):
        PolicyEngine.from_yaml(content)


@pytest.mark.parametrize(
    "content", ["", "# no overrides", "null", "{}", "rules: {}", "rules:\n  fare_comparison: {}"]
)
def test_policy_engine_omitted_rules_preserve_defaults(content: str) -> None:
    engine = PolicyEngine.from_yaml(content)
    assert len(engine.rules) == 9
    context = PolicyContext(selected_fare=Decimal("401"), lowest_fare=Decimal("200"))
    result = next(r for r in engine.validate(context) if r.rule_id == "fare_comparison")
    assert result.passed is False
    assert result.severity == Severity.BLOCKING
    assert "200" in result.message


def test_policy_engine_invalid_config_rejected_from_file_and_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = "rules:\n  fare_comparision: {max_over_lowest: 5}"
    path = tmp_path / "policy.yaml"
    path.write_text(content, encoding="utf-8")
    monkeypatch.setenv("TEST_POLICY_YAML", content)
    for load in (
        lambda: PolicyEngine.from_file(path),
        lambda: PolicyEngine.from_environment("TEST_POLICY_YAML"),
    ):
        with pytest.raises(
            ValueError, match="policy.yaml: unknown rule.*fare_comparision"
        ):
            load()
