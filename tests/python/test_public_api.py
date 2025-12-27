"""Tests for package public API exports."""

from __future__ import annotations

import importlib


def test_public_api_imports() -> None:
    """Package root should expose the documented API symbols."""
    travel_plan_permission = importlib.import_module("travel_plan_permission")

    from travel_plan_permission import (
        TripPlan,
        check_trip_plan,
        fill_travel_spreadsheet,
        list_allowed_vendors,
        reconcile,
    )

    assert travel_plan_permission.__version__
    assert TripPlan is not None
    assert check_trip_plan is not None
    assert list_allowed_vendors is not None
    assert reconcile is not None
    assert fill_travel_spreadsheet is not None
