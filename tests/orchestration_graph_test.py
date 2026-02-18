import json
import os
from pathlib import Path

import pytest

from travel_plan_permission.canonical import CanonicalTripPlan, load_trip_plan_input
from travel_plan_permission.models import TripPlan
from travel_plan_permission.orchestration import graph as orchestration_graph


def _fixture_trip_input() -> tuple[TripPlan, CanonicalTripPlan | None]:
    fixture_path = (
        Path(__file__).resolve().parent / "fixtures" / "sample_trip_plan_minimal.json"
    )
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    trip_input = load_trip_plan_input(payload)
    return trip_input.plan, trip_input.canonical


def _require_langgraph() -> None:
    if os.getenv("CI"):
        __import__("langgraph")
    else:
        pytest.importorskip("langgraph")


def test_langgraph_compiled_path_creates_spreadsheet(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_langgraph()
    plan, canonical = _fixture_trip_input()

    graph = orchestration_graph.build_policy_graph(prefer_langgraph=True)
    assert graph.__class__.__name__ == "_LangGraphPolicyGraph"

    compiled = graph._compiled  # type: ignore[attr-defined]
    called = {"value": False}
    original_invoke = compiled.invoke

    def _tracking_invoke(
        state: orchestration_graph.TripState,
    ) -> orchestration_graph.TripState:
        called["value"] = True
        return original_invoke(state)

    monkeypatch.setattr(compiled, "invoke", _tracking_invoke)

    output_path = tmp_path / "travel_request_langgraph.xlsx"
    state = graph.invoke(
        orchestration_graph.TripState(
            plan_json=plan.model_dump(mode="json"),
            canonical_plan=(
                canonical.model_dump(mode="json") if canonical is not None else None
            ),
            spreadsheet_path=output_path,
        )
    )

    assert called["value"] is True
    assert state.spreadsheet_path == str(output_path)
    assert output_path.exists()
