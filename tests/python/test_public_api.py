"""Tests for package public API exports."""

from __future__ import annotations

import importlib


def test_public_api_imports() -> None:
    """Package root should expose the documented API symbols."""
    travel_plan_permission = importlib.import_module("travel_plan_permission")

    from travel_plan_permission import (
        PolicyCheckResult,
        PolicyIssue,
        Receipt,
        ReconciliationResult,
        TripPlan,
        check_trip_plan,
        fill_travel_spreadsheet,
        list_allowed_vendors,
        reconcile,
    )

    required_exports = {
        "PolicyCheckResult",
        "PolicyIssue",
        "Receipt",
        "ReconciliationResult",
        "TripPlan",
        "check_trip_plan",
        "fill_travel_spreadsheet",
        "list_allowed_vendors",
        "reconcile",
        "__version__",
    }
    assert required_exports.issubset(set(travel_plan_permission.__all__))
    assert travel_plan_permission.__version__
    assert TripPlan is not None
    assert check_trip_plan is not None
    assert list_allowed_vendors is not None
    assert reconcile is not None
    assert fill_travel_spreadsheet is not None
    assert PolicyCheckResult is not None
    assert PolicyIssue is not None
    assert ReconciliationResult is not None
    assert Receipt is not None
