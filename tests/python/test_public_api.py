"""Tests for package root public API imports."""

from __future__ import annotations

import tomllib
from pathlib import Path

import travel_plan_permission as tpp
from travel_plan_permission import (
    TripPlan,
    __version__,
    check_trip_plan,
    fill_travel_spreadsheet,
    list_allowed_vendors,
    reconcile,
)


def test_public_api_exports() -> None:
    """Core API symbols should be importable from the package root."""
    required_exports = {
        "__version__",
        "TripPlan",
        "check_trip_plan",
        "fill_travel_spreadsheet",
        "list_allowed_vendors",
        "reconcile",
    }

    assert required_exports.issubset(set(tpp.__all__))
    assert callable(check_trip_plan)
    assert callable(list_allowed_vendors)
    assert callable(reconcile)
    assert callable(fill_travel_spreadsheet)
    assert TripPlan is not None


def test_version_matches_pyproject() -> None:
    """Package __version__ should align with pyproject.toml."""
    pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
    pyproject_data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    assert __version__ == pyproject_data["project"]["version"]
