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

    state = TripState(
        plan_json=trip_input.plan,
        canonical_plan=trip_input.canonical,
        spreadsheet_path=str(tmp_path / "travel_request.xlsx"),
    )

    json.dumps(state.model_dump(mode="json"))
