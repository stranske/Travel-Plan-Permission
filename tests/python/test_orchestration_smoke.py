from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from travel_plan_permission.models import TripPlan
from travel_plan_permission.orchestration import run_policy_graph


def test_policy_graph_smoke(tmp_path: Path) -> None:
    plan = TripPlan(
        trip_id="TRIP-ORCH-TEST",
        traveler_name="Jordan Lee",
        destination="Seattle, WA 98101",
        departure_date=date(2025, 4, 10),
        return_date=date(2025, 4, 12),
        purpose="Client meetings",
        estimated_cost=Decimal("980.00"),
    )

    output_path = tmp_path / "travel_request.xlsx"
    state = run_policy_graph(plan, output_path=output_path, prefer_langgraph=False)

    assert state.policy_result is not None
    assert state.policy_result.status == "fail"
    assert state.spreadsheet_path == output_path
    assert output_path.exists()


def test_policy_graph_langgraph_smoke(tmp_path: Path) -> None:
    pytest.importorskip("langgraph")
    plan = TripPlan(
        trip_id="TRIP-LANGGRAPH-TEST",
        traveler_name="Jordan Lee",
        destination="Seattle, WA 98101",
        departure_date=date(2025, 4, 10),
        return_date=date(2025, 4, 12),
        purpose="Client meetings",
        estimated_cost=Decimal("980.00"),
    )

    output_path = tmp_path / "travel_request_langgraph.xlsx"
    state = run_policy_graph(plan, output_path=output_path, prefer_langgraph=True)

    assert state.policy_result is not None
    assert state.spreadsheet_path == output_path
    assert output_path.exists()
