from __future__ import annotations

from datetime import date

import travel_plan_permission.policy_lite as policy_lite
from travel_plan_permission import PolicyContext


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
    assert "local_overnight" in by_rule
    assert by_rule["local_overnight"].missing_fields == ["distance_from_office_miles"]
