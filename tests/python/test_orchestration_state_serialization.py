import json
from pathlib import Path

from travel_plan_permission.canonical import load_trip_plan_input
from travel_plan_permission.orchestration import TripState
from travel_plan_permission.policy_api import UnfilledMappingReport, check_trip_plan
from travel_plan_permission.policy_lite import RuleDiagnostic


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


def test_trip_state_coerces_assigned_policy_result(tmp_path: Path) -> None:
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

    policy_result = check_trip_plan(trip_input.plan)
    state.policy_result = policy_result

    assert isinstance(state.policy_result, dict)
    assert state.policy_result["status"] == policy_result.status
    json.dumps(state.model_dump(mode="json"))


def test_trip_state_coerces_assigned_policy_missing_inputs(tmp_path: Path) -> None:
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

    state.policy_missing_inputs = [
        RuleDiagnostic(
            rule_id="advance_booking",
            missing_fields=["booking_date"],
            message="Missing required inputs: booking_date (rule 'advance_booking').",
        )
    ]

    assert state.policy_missing_inputs == [
        {
            "rule_id": "advance_booking",
            "missing_fields": ["booking_date"],
            "message": "Missing required inputs: booking_date (rule 'advance_booking').",
        }
    ]
    json.dumps(state.model_dump(mode="json"))


def test_trip_state_coerces_assigned_unfilled_mapping_report(tmp_path: Path) -> None:
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

    report = UnfilledMappingReport()
    report.add("cells", "event_registration_cost", "B2", "invalid_currency")
    report.add("dropdowns", "department", "B3", "missing")

    state.unfilled_mapping_report = report

    assert state.unfilled_mapping_report == {
        "cells": [
            {
                "field": "event_registration_cost",
                "cell": "B2",
                "reason": "invalid_currency",
            }
        ],
        "dropdowns": [
            {
                "field": "department",
                "cell": "B3",
                "reason": "missing",
            }
        ],
        "checkboxes": [],
    }
    json.dumps(state.model_dump(mode="json"))


def test_trip_state_accepts_dict_unfilled_mapping_report(tmp_path: Path) -> None:
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

    report = {
        "cells": [{"field": "purpose", "cell": "B5", "reason": "missing"}],
        "dropdowns": [],
        "checkboxes": [],
    }
    state.unfilled_mapping_report = report

    assert state.unfilled_mapping_report == report
    json.dumps(state.model_dump(mode="json"))
