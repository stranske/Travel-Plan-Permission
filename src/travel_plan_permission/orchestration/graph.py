"""Minimal orchestration graph for policy checks and artifacts."""

from __future__ import annotations

import importlib
import tempfile
from pathlib import Path
from typing import Any, Protocol, cast

from pydantic import BaseModel, Field

from ..canonical import CanonicalTripPlan
from ..models import TripPlan
from ..policy_api import (
    PolicyCheckResult,
    check_trip_plan,
    fill_travel_spreadsheet,
    render_travel_spreadsheet_bytes,
)


class TripState(BaseModel):
    """State container for the orchestration flow."""

    plan: TripPlan
    canonical_plan: CanonicalTripPlan | None = None
    policy_result: PolicyCheckResult | None = None
    spreadsheet_path: Path | None = None
    errors: list[str] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}


class PolicyGraph(Protocol):
    """Minimal interface for invoking orchestration graphs."""

    def invoke(self, state: TripState) -> TripState: ...


def _default_spreadsheet_path(plan: TripPlan) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="travel_plan_"))
    return temp_dir / f"{plan.trip_id}_request.xlsx"


def _policy_check_node(state: TripState) -> TripState:
    state.policy_result = check_trip_plan(state.plan)
    return state


def _spreadsheet_node(state: TripState) -> TripState:
    output_path = state.spreadsheet_path or _default_spreadsheet_path(state.plan)
    if state.spreadsheet_path is None:
        spreadsheet_bytes = render_travel_spreadsheet_bytes(
            state.plan,
            canonical_plan=state.canonical_plan,
        )
        output_path.write_bytes(spreadsheet_bytes)
        state.spreadsheet_path = output_path
    else:
        state.spreadsheet_path = fill_travel_spreadsheet(
            state.plan,
            output_path,
            canonical_plan=state.canonical_plan,
        )
    return state


class _SimplePolicyGraph:
    def invoke(self, state: TripState) -> TripState:
        state = _policy_check_node(state)
        state = _spreadsheet_node(state)
        return state


class _LangGraphPolicyGraph:
    def __init__(self, compiled: Any) -> None:
        self._compiled = compiled

    def invoke(self, state: TripState) -> TripState:
        return cast(TripState, self._compiled.invoke(state))


def _build_langgraph() -> PolicyGraph | None:
    try:
        langgraph_graph = importlib.import_module("langgraph.graph")
    except ImportError:
        return None

    END = langgraph_graph.END
    StateGraph = langgraph_graph.StateGraph

    graph = StateGraph(TripState)
    graph.add_node("policy_check", _policy_check_node)
    graph.add_node("spreadsheet", _spreadsheet_node)
    graph.add_edge("policy_check", "spreadsheet")
    graph.add_edge("spreadsheet", END)
    graph.set_entry_point("policy_check")
    compiled = graph.compile()
    return _LangGraphPolicyGraph(compiled)


def build_policy_graph(*, prefer_langgraph: bool = True) -> PolicyGraph:
    """Create an orchestration graph, using LangGraph when available."""

    if prefer_langgraph:
        compiled = _build_langgraph()
        if compiled is not None:
            return compiled
    return _SimplePolicyGraph()


def run_policy_graph(
    plan: TripPlan,
    *,
    canonical_plan: CanonicalTripPlan | None = None,
    output_path: Path | str | None = None,
    prefer_langgraph: bool = True,
) -> TripState:
    """Run the policy graph over a trip plan and return the final state."""

    spreadsheet_path = Path(output_path) if output_path is not None else None
    graph = build_policy_graph(prefer_langgraph=prefer_langgraph)
    state = TripState(
        plan=plan,
        canonical_plan=canonical_plan,
        spreadsheet_path=spreadsheet_path,
    )
    return graph.invoke(state)
