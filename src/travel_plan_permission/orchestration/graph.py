"""Minimal orchestration graph for policy checks and artifacts."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

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

    model_config = ConfigDict(validate_assignment=True)

    plan_json: dict[str, object]
    canonical_plan: dict[str, object] | None = None
    policy_result: dict[str, object] | None = None
    spreadsheet_path: str | None = None
    errors: list[str] = Field(default_factory=list)

    @field_validator("plan_json", mode="before")
    @classmethod
    def _coerce_plan(cls, value: object) -> dict[str, object]:
        if isinstance(value, TripPlan):
            return value.model_dump(mode="json")
        if isinstance(value, dict):
            return TripPlan.model_validate(value).model_dump(mode="json")
        return value  # type: ignore[return-value]

    @field_validator("canonical_plan", mode="before")
    @classmethod
    def _coerce_canonical_plan(cls, value: object) -> dict[str, object] | None:
        if value is None:
            return None
        if isinstance(value, CanonicalTripPlan):
            return value.model_dump(mode="json")
        if isinstance(value, dict):
            return CanonicalTripPlan.model_validate(value).model_dump(mode="json")
        return value  # type: ignore[return-value]

    @field_validator("spreadsheet_path", mode="before")
    @classmethod
    def _coerce_spreadsheet_path(cls, value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, Path):
            return str(value)
        return value  # type: ignore[return-value]

    @field_validator("policy_result", mode="before")
    @classmethod
    def _coerce_policy_result(cls, value: object) -> dict[str, object] | None:
        if value is None:
            return None
        if isinstance(value, PolicyCheckResult):
            return value.model_dump(mode="json")
        if isinstance(value, dict):
            return PolicyCheckResult.model_validate(value).model_dump(mode="json")
        return value  # type: ignore[return-value]

    @field_serializer("plan_json", mode="plain")
    def _serialize_plan(self, value: object) -> dict[str, object]:
        if isinstance(value, TripPlan):
            return value.model_dump(mode="json")
        return value  # type: ignore[return-value]

    @field_serializer("canonical_plan", mode="plain")
    def _serialize_canonical_plan(self, value: object) -> dict[str, object] | None:
        if isinstance(value, CanonicalTripPlan):
            return value.model_dump(mode="json")
        return value  # type: ignore[return-value]

    @field_serializer("spreadsheet_path", mode="plain")
    def _serialize_spreadsheet_path(self, value: object) -> str | None:
        if isinstance(value, Path):
            return str(value)
        return value  # type: ignore[return-value]


class PolicyGraph(Protocol):
    """Minimal interface for invoking orchestration graphs."""

    def invoke(self, state: TripState) -> TripState: ...


def _default_spreadsheet_path(plan: TripPlan) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="travel_plan_"))
    return temp_dir / f"{plan.trip_id}_request.xlsx"


def _load_plan(state: TripState) -> TripPlan:
    return TripPlan.model_validate(state.plan_json)


def _load_canonical_plan(state: TripState) -> CanonicalTripPlan | None:
    if state.canonical_plan is None:
        return None
    return CanonicalTripPlan.model_validate(state.canonical_plan)


def _policy_check_node(state: TripState) -> TripState:
    plan = _load_plan(state)
    state.policy_result = check_trip_plan(plan)
    return state


def _spreadsheet_node(state: TripState) -> TripState:
    plan = _load_plan(state)
    canonical_plan = _load_canonical_plan(state)
    output_path = (
        Path(state.spreadsheet_path)
        if state.spreadsheet_path is not None
        else _default_spreadsheet_path(plan)
    )
    if state.spreadsheet_path is None:
        spreadsheet_bytes = render_travel_spreadsheet_bytes(
            plan,
            canonical_plan=canonical_plan,
        )
        output_path.write_bytes(spreadsheet_bytes)
        state.spreadsheet_path = str(output_path)
    else:
        output_path = fill_travel_spreadsheet(
            plan,
            output_path,
            canonical_plan=canonical_plan,
        )
        state.spreadsheet_path = str(output_path)
    return state


class _SimplePolicyGraph:
    def invoke(self, state: TripState) -> TripState:
        state = _policy_check_node(state)
        state = _spreadsheet_node(state)
        return state


def _build_langgraph() -> PolicyGraph | None:
    try:
        from langgraph.graph import END, StateGraph  # type: ignore[import-not-found]
    except ImportError:
        return None

    graph = StateGraph(TripState)
    graph.add_node("policy_check", _policy_check_node)
    graph.add_node("spreadsheet", _spreadsheet_node)
    graph.add_edge("policy_check", "spreadsheet")
    graph.add_edge("spreadsheet", END)
    graph.set_entry_point("policy_check")
    return graph.compile()  # type: ignore[no-any-return]


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

    spreadsheet_path = str(Path(output_path)) if output_path is not None else None
    graph = build_policy_graph(prefer_langgraph=prefer_langgraph)
    state = TripState(
        plan_json=plan.model_dump(mode="json"),
        canonical_plan=(
            canonical_plan.model_dump(mode="json") if canonical_plan is not None else None
        ),
        spreadsheet_path=spreadsheet_path,
    )
    return graph.invoke(state)
