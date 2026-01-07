import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from travel_plan_permission.models import TripPlan
from travel_plan_permission.orchestration import run_policy_graph


def test_policy_graph_smoke(tmp_path: Path) -> None:
    plan = TripPlan(
        trip_id="TRIP-ORCH-TEST",
        traveler_name="Jordan Lee",
        destination="Seattle, WA 98101",
        departure_date=date(2025, 4, 10),
        return_date=date(2025, 4, 12),
        purpose="Client meetings",
        estimated_cost=Decimal("980.00"),
    )

    output_path = tmp_path / "travel_request.xlsx"
    state = run_policy_graph(plan, output_path=output_path, prefer_langgraph=False)

    assert state.policy_result is not None
    assert isinstance(state.policy_result, dict)
    assert state.policy_result["status"] == "fail"
    assert isinstance(state.policy_missing_inputs, list)
    assert state.unfilled_mapping_report is not None
    assert state.spreadsheet_path == str(output_path)
    assert output_path.exists()
    serialized = state.model_dump(mode="json")
    assert isinstance(serialized["policy_result"], dict)
    assert serialized["policy_result"]["status"] == "fail"
    assert isinstance(serialized["policy_missing_inputs"], list)
    assert serialized["unfilled_mapping_report"] is not None
    json.dumps(serialized)


def test_policy_graph_records_missing_policy_inputs(tmp_path: Path) -> None:
    plan = TripPlan(
        trip_id="TRIP-ORCH-MISSING",
        traveler_name="Sam Parker",
        destination="Seattle, WA 98101",
        departure_date=date(2025, 5, 10),
        return_date=date(2025, 5, 12),
        purpose="Project kickoff",
        estimated_cost=Decimal("650.00"),
    )

    output_path = tmp_path / "travel_request.xlsx"
    state = run_policy_graph(plan, output_path=output_path, prefer_langgraph=False)

    missing = state.policy_missing_inputs
    assert missing
    rule_ids = {entry.get("rule_id") for entry in missing}
    assert "advance_booking" in rule_ids
    advance_booking = next(entry for entry in missing if entry.get("rule_id") == "advance_booking")
    assert "booking_date" in advance_booking.get("missing_fields", [])
