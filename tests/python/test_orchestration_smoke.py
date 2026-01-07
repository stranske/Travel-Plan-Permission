import json
from pathlib import Path

import pytest

from travel_plan_permission.canonical import CanonicalTripPlan, load_trip_plan_input
from travel_plan_permission.models import TripPlan
from travel_plan_permission.orchestration import build_policy_graph, run_policy_graph


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
    assert state.spreadsheet_path == str(output_path)
    assert output_path.exists()
    serialized = state.model_dump(mode="json")
    assert isinstance(serialized["policy_result"], dict)
    assert serialized["policy_result"]["status"] == "fail"
    json.dumps(serialized)


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
