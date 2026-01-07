import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from travel_plan_permission import policy_api
from travel_plan_permission.canonical import CanonicalTripPlan, load_trip_plan_input
from travel_plan_permission.mapping import TemplateMapping
from travel_plan_permission.models import ExpenseCategory, TripPlan
from travel_plan_permission.orchestration import build_policy_graph, run_policy_graph
from travel_plan_permission.orchestration import graph as orchestration_graph


def _fixture_trip_input() -> tuple[TripPlan, CanonicalTripPlan | None]:
    fixture_path = (
        Path(__file__).resolve().parents[1] / "fixtures" / "sample_trip_plan_minimal.json"
    )
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    trip_input = load_trip_plan_input(payload)
    return trip_input.plan, trip_input.canonical


def test_policy_graph_smoke(tmp_path: Path) -> None:
    plan, canonical = _fixture_trip_input()

    output_path = tmp_path / "travel_request.xlsx"
    state = run_policy_graph(
        plan,
        canonical_plan=canonical,
        output_path=output_path,
        prefer_langgraph=False,
    )

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


@pytest.mark.filterwarnings("ignore:Pydantic serializer warnings.*:UserWarning")
def test_spreadsheet_node_records_unfilled_mapping_report_entries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    plan = TripPlan(
        trip_id="TRIP-ORCH-REPORT",
        traveler_name="Jordan Lee",
        destination="Austin, TX 78701",
        departure_date=date(2025, 4, 10),
        return_date=date(2025, 4, 12),
        purpose="Conference planning",
        estimated_cost=Decimal("1200.00"),
    )
    invalid_plan = TripPlan.model_construct(
        trip_id=plan.trip_id,
        traveler_name=plan.traveler_name,
        destination=plan.destination,
        departure_date=123,
        return_date=123,
        purpose=plan.purpose,
        estimated_cost=plan.estimated_cost,
        expense_breakdown={ExpenseCategory.CONFERENCE_FEES: object()},
    )
    mapping = TemplateMapping(
        version="ITIN-2025.1",
        cells={
            "event_registration_cost": "B2",
            "depart_date": "B3",
            "nonexistent_field": "B4",
        },
        dropdowns={},
        checkboxes={},
        formulas={},
        metadata={},
    )
    output_path = tmp_path / "travel_request.xlsx"
    state = orchestration_graph.TripState(
        plan_json=plan.model_dump(mode="json"),
        spreadsheet_path=output_path,
    )

    monkeypatch.setattr(policy_api, "load_template_mapping", lambda: mapping)
    monkeypatch.setattr(orchestration_graph, "_load_plan", lambda _: invalid_plan)

    state = orchestration_graph._spreadsheet_node(state)

    report = state.unfilled_mapping_report
    assert report is not None
    cells = {(entry["field"], entry["reason"]) for entry in report["cells"]}
    assert ("event_registration_cost", "invalid_currency") in cells
    assert ("depart_date", "invalid_date") in cells
    assert ("nonexistent_field", "missing") in cells


def test_policy_graph_langgraph_smoke(tmp_path: Path) -> None:
    pytest.importorskip("langgraph")
    plan, canonical = _fixture_trip_input()

    output_path = tmp_path / "travel_request_langgraph.xlsx"
    state = run_policy_graph(
        plan,
        canonical_plan=canonical,
        output_path=output_path,
        prefer_langgraph=True,
    )

    assert state.policy_result is not None
    assert isinstance(state.policy_result, dict)
    assert state.policy_result["status"] == "fail"
    assert state.spreadsheet_path == str(output_path)
    assert output_path.exists()


def test_policy_graph_prefers_langgraph_when_available() -> None:
    pytest.importorskip("langgraph")

    graph = build_policy_graph(prefer_langgraph=True)

    assert graph.__class__.__name__ == "_LangGraphPolicyGraph"
