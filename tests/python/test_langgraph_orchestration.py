import json
import os
from pathlib import Path

import pytest

from travel_plan_permission.canonical import CanonicalTripPlan, load_trip_plan_input
from travel_plan_permission.models import TripPlan
from travel_plan_permission.orchestration import run_policy_graph


def _fixture_trip_input() -> tuple[TripPlan, CanonicalTripPlan | None]:
    fixture_path = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "sample_trip_plan_minimal.json"
    )
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    trip_input = load_trip_plan_input(payload)
    return trip_input.plan, trip_input.canonical


def _require_langgraph() -> None:
    if os.getenv("CI"):
        __import__("langgraph")
    else:
        pytest.importorskip("langgraph")


def test_policy_graph_runs_with_langgraph(tmp_path: Path) -> None:
    _require_langgraph()
    plan, canonical = _fixture_trip_input()

    output_path = tmp_path / "travel_request_langgraph.xlsx"
    state = run_policy_graph(
        plan,
        canonical_plan=canonical,
        output_path=output_path,
        prefer_langgraph=True,
    )

    assert state.policy_result is not None
    assert state.spreadsheet_path == str(output_path)
    assert output_path.exists()
