import json
from pathlib import Path

from travel_plan_permission.canonical import load_trip_plan_input
from travel_plan_permission.orchestration import TripState


def test_trip_state_coerces_plans_to_json(tmp_path: Path) -> None:
    fixture_path = (
        Path(__file__).resolve().parents[1] / "fixtures" / "canonical_trip_plan_realistic.json"
    )
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    trip_input = load_trip_plan_input(payload)
    spreadsheet_path = tmp_path / "travel_request.xlsx"

    state = TripState(
        plan_json=trip_input.plan,
        canonical_plan=trip_input.canonical,
        spreadsheet_path=spreadsheet_path,
    )

    assert isinstance(state.plan_json, dict)
    assert isinstance(state.canonical_plan, dict)
    assert state.spreadsheet_path == str(spreadsheet_path)
    json.dumps(state.model_dump(mode="json"))
