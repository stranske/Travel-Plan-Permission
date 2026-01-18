from datetime import date
from decimal import Decimal

from travel_plan_permission import (
    ExpenseCategory,
    ExpenseItem,
    PolicyContext,
    PolicyEngine,
    Severity,
)


def test_policy_engine_evaluates_all_rules():
    yaml_content = """
rules:
  advance_booking:
    days_required: 10
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
        "advance_booking",
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

    assert not results["advance_booking"].passed
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
    assert len(results) == 10
    assert all(result.passed for result in results)
    assert engine.blocking_results(context) == []


def test_policy_messages_include_thresholds_from_config():
    engine = PolicyEngine.from_yaml("""
rules:
  advance_booking:
    days_required: 21
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

    advance = results["advance_booking"]
    assert not advance.passed
    assert "21" in advance.message

    fare = results["fare_comparison"]
    assert not fare.passed
    assert "175" in fare.message
