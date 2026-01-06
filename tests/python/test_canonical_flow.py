import json
import re
from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook

from travel_plan_permission.canonical import load_trip_plan_input
from travel_plan_permission.policy_api import check_trip_plan, render_travel_spreadsheet_bytes


def test_canonical_trip_plan_flow_renders_policy_and_spreadsheet() -> None:
    fixture_path = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "canonical_trip_plan_realistic.json"
    )
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))

    trip_input = load_trip_plan_input(payload)

    assert trip_input.canonical is not None
    assert trip_input.plan.traveler_name == trip_input.canonical.traveler_name
    assert trip_input.plan.destination.endswith(trip_input.canonical.destination_zip)

    policy_result = check_trip_plan(trip_input.plan)
    policy_dump = policy_result.model_dump()
    assert set(policy_dump) == {"status", "issues", "policy_version"}
    assert policy_dump["status"] in ("pass", "fail")
    assert isinstance(policy_dump["issues"], list)
    assert re.fullmatch(r"[0-9a-f]{64}", policy_dump["policy_version"])
    if policy_result.issues:
        issue_dump = policy_result.issues[0].model_dump()
        assert set(issue_dump) == {"code", "message", "severity", "context"}

    output_bytes = render_travel_spreadsheet_bytes(
        trip_input.plan, canonical_plan=trip_input.canonical
    )
    assert isinstance(output_bytes, bytes)
    assert output_bytes

    workbook = load_workbook(BytesIO(output_bytes))
    sheet = workbook.active

    assert sheet["B3"].value == "Alex Rivera"
    assert sheet["B4"].value == "Regional partner summit"
    assert sheet["D4"].value == "OPS-410"
    assert sheet["B5"].value == "Seattle, WA"
    assert sheet["F5"].value == "98101"
    assert sheet["B11"].value == "Pine Street Suites"
    assert sheet["G12"].value == "X"
    workbook.close()
