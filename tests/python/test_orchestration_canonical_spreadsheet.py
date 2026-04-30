import json
from pathlib import Path

from openpyxl import load_workbook

from travel_plan_permission.canonical import load_trip_plan_input
from travel_plan_permission.orchestration import run_policy_graph


def test_policy_graph_retains_canonical_fields(tmp_path: Path) -> None:
    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "sample_trip_plan_rich.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    trip_input = load_trip_plan_input(payload)
    assert trip_input.canonical is not None

    output_path = tmp_path / "travel_request.xlsx"
    state = run_policy_graph(
        trip_input.plan,
        canonical_plan=trip_input.canonical,
        output_path=output_path,
        prefer_langgraph=False,
    )

    assert state.spreadsheet_path == str(output_path)

    workbook = load_workbook(output_path)
    sheet = workbook.active

    assert sheet["B8"].value == "UA204"
    assert sheet["B11"].value == "Harborview Suites"
    assert sheet["B12"].value == "88 Mission St"
    assert sheet["D12"].value == "San Francisco, CA"
    workbook.close()


def test_policy_graph_state_is_json_serializable(tmp_path: Path) -> None:
    fixture_path = (
        Path(__file__).resolve().parents[1] / "fixtures" / "canonical_trip_plan_realistic.json"
    )
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    trip_input = load_trip_plan_input(payload)

    output_path = tmp_path / "travel_request.xlsx"
    state = run_policy_graph(
        trip_input.plan,
        canonical_plan=trip_input.canonical,
        output_path=output_path,
        prefer_langgraph=False,
    )

    json.dumps(state.model_dump(mode="json"))
