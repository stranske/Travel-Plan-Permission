"""Runnable orchestration example."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

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


def main() -> int:
    plan = _sample_plan()
    output_path = Path.cwd() / "travel_request_example.xlsx"
    state = run_policy_graph(plan, output_path=output_path)

    if state.policy_result is None:
        raise RuntimeError("No policy result returned from orchestration graph.")

    print(f"Policy status: {state.policy_result.status}")
    print(f"Spreadsheet: {state.spreadsheet_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
