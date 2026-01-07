"""Runnable orchestration example."""

from __future__ import annotations

import json
from argparse import ArgumentParser, Namespace
from datetime import date
from decimal import Decimal
from pathlib import Path

from ..canonical import TripPlanInput, load_trip_plan_input
from ..models import ExpenseCategory, TripPlan
from .graph import run_policy_graph


def _sample_plan() -> TripPlan:
    return TripPlan(
        trip_id="TRIP-ORCH-001",
        traveler_name="Alex Rivera",
        destination="Chicago, IL 60601",
        departure_date=date(2025, 6, 10),
        return_date=date(2025, 6, 12),
        purpose="Quarterly planning summit",
        estimated_cost=Decimal("1200.50"),
        expense_breakdown={
            ExpenseCategory.AIRFARE: Decimal("420.50"),
            ExpenseCategory.LODGING: Decimal("600.00"),
            ExpenseCategory.MEALS: Decimal("180.00"),
        },
    )


def _parse_args() -> Namespace:
    parser = ArgumentParser(description="Run the minimal policy orchestration flow.")
    parser.add_argument(
        "--minimal-json",
        type=Path,
        help="Path to a minimal intake JSON payload to convert before running the graph.",
    )
    parser.add_argument(
        "--trip-id",
        default="TRIP-ORCH-001",
        help="Trip ID to use when converting minimal intake payloads.",
    )
    parser.add_argument(
        "--origin-city",
        help="Origin city to use when converting minimal intake payloads.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path.cwd() / "travel_request_example.xlsx",
        help="Where to write the travel request spreadsheet.",
    )
    parser.add_argument(
        "--no-langgraph",
        action="store_true",
        help="Force the fallback graph instead of LangGraph.",
    )
    return parser.parse_args()


def _plan_input_from_minimal(
    path: Path,
    trip_id: str,
    origin_city: str | None,
) -> TripPlanInput:
    payload = json.loads(path.read_text(encoding="utf-8"))
    plan_input = load_trip_plan_input(payload)
    overrides: dict[str, object] = {"trip_id": trip_id}
    if origin_city is not None:
        overrides["origin_city"] = origin_city
    plan = plan_input.plan.model_copy(update=overrides)
    return TripPlanInput(plan=plan, canonical=plan_input.canonical)


def main() -> int:
    args = _parse_args()
    if args.minimal_json:
        plan_input = _plan_input_from_minimal(
            args.minimal_json,
            args.trip_id,
            args.origin_city,
        )
        plan = plan_input.plan
        canonical_plan = plan_input.canonical
    else:
        plan = _sample_plan()
        canonical_plan = None
    output_path = args.output
    state = run_policy_graph(
        plan,
        canonical_plan=canonical_plan,
        output_path=output_path,
        prefer_langgraph=not args.no_langgraph,
    )

    if state.policy_result is None:
        raise RuntimeError("No policy result returned from orchestration graph.")

    print(f"Policy status: {state.policy_result['status']}")
    if state.policy_missing_inputs:
        print("Missing policy inputs:")
        print(json.dumps(state.policy_missing_inputs, indent=2))
    if state.unfilled_mapping_report is not None:
        print("Unfilled mapping report:")
        print(json.dumps(state.unfilled_mapping_report, indent=2))
    print(f"Spreadsheet: {state.spreadsheet_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
