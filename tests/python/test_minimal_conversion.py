import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from travel_plan_permission import ExpenseCategory, trip_plan_from_minimal


def test_trip_plan_from_minimal_builds_plan() -> None:
    payload = json.loads(
        Path("tests/fixtures/sample_trip_plan_minimal.json").read_text(encoding="utf-8")
    )

    plan = trip_plan_from_minimal(
        payload,
        trip_id="TRIP-1001",
        origin_city="Austin, TX",
    )

    assert plan.trip_id == "TRIP-1001"
    assert plan.traveler_name == payload["traveler_name"]
    assert plan.purpose == payload["business_purpose"]
    assert plan.destination == f"{payload['city_state']} {payload['destination_zip']}"
    assert plan.origin_city == "Austin, TX"
    assert plan.departure_date == date.fromisoformat(payload["depart_date"])
    assert plan.return_date == date.fromisoformat(payload["return_date"])

    expected_airfare = Decimal("550")
    expected_lodging = Decimal("210") * Decimal("3")
    expected_fees = Decimal("350")
    expected_parking = Decimal("36")
    expected_total = expected_airfare + expected_lodging + expected_fees + expected_parking

    assert plan.estimated_cost == expected_total
    assert plan.expense_breakdown[ExpenseCategory.AIRFARE] == expected_airfare
    assert plan.expense_breakdown[ExpenseCategory.LODGING] == expected_lodging
    assert plan.expense_breakdown[ExpenseCategory.CONFERENCE_FEES] == expected_fees
    assert plan.expense_breakdown[ExpenseCategory.GROUND_TRANSPORT] == expected_parking
