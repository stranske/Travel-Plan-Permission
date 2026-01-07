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


def test_trip_state_coerces_dict_plans_to_json(tmp_path: Path) -> None:
    fixture_path = (
        Path(__file__).resolve().parents[1] / "fixtures" / "canonical_trip_plan_realistic.json"
    )
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    trip_input = load_trip_plan_input(payload)
    assert trip_input.canonical is not None
    spreadsheet_path = tmp_path / "travel_request.xlsx"

    state = TripState(
        plan_json=trip_input.plan.model_dump(),
        canonical_plan=trip_input.canonical.model_dump(),
        spreadsheet_path=spreadsheet_path,
    )

    assert isinstance(state.plan_json, dict)
    assert isinstance(state.canonical_plan, dict)
    json.dumps(state.model_dump(mode="json"))


def test_trip_state_serializes_assigned_models(tmp_path: Path) -> None:
    fixture_path = (
        Path(__file__).resolve().parents[1] / "fixtures" / "canonical_trip_plan_realistic.json"
    )
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    trip_input = load_trip_plan_input(payload)
    spreadsheet_path = tmp_path / "travel_request.xlsx"

    state = TripState(
        plan_json=trip_input.plan.model_dump(mode="json"),
        canonical_plan=(
            trip_input.canonical.model_dump(mode="json") if trip_input.canonical else None
        ),
        spreadsheet_path=spreadsheet_path,
    )

    state.plan_json = trip_input.plan
    state.canonical_plan = trip_input.canonical

    assert isinstance(state.plan_json, dict)
    assert isinstance(state.canonical_plan, dict)
    json.dumps(state.model_dump(mode="json"))


def test_trip_state_coerces_assigned_spreadsheet_path(tmp_path: Path) -> None:
    fixture_path = (
        Path(__file__).resolve().parents[1] / "fixtures" / "canonical_trip_plan_realistic.json"
    )
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    trip_input = load_trip_plan_input(payload)
    spreadsheet_path = tmp_path / "travel_request.xlsx"

    state = TripState(
        plan_json=trip_input.plan.model_dump(mode="json"),
        canonical_plan=(
            trip_input.canonical.model_dump(mode="json") if trip_input.canonical else None
        ),
        spreadsheet_path=str(spreadsheet_path),
    )

    state.spreadsheet_path = spreadsheet_path

    assert state.spreadsheet_path == str(spreadsheet_path)
    json.dumps(state.model_dump(mode="json"))
