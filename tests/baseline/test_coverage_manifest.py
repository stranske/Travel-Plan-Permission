"""Coverage manifest -- which flat metric keys are exercised; emit a report.

Uses the generic ``baseline_kit.CoverageManifest``. A metric counts as exercised
when at least one directional check holds for its measured scenario and control.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from baseline_kit import CoverageManifest, evaluate_direction

from . import adapter
from .conftest import REPO_ROOT

REPORT_PATH = REPO_ROOT / "docs" / "reports" / "baseline-coverage.md"


@pytest.fixture(scope="module")
def measured_scenarios(catalog: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Evaluate each catalog input through the supported adapter entry point."""
    base_request = catalog["base"]["request"]
    return {
        scenario["id"]: adapter.run_scenario(scenario, base_request)
        for scenario in catalog["scenarios"]
    }


@pytest.fixture(scope="module")
def manifest(
    catalog: dict[str, Any], measured_scenarios: dict[str, dict[str, float]]
) -> CoverageManifest:
    touched: set[str] = set()
    for check in catalog["directionals"]:
        metric = check["metric"]
        variant = measured_scenarios[check["scenario"]].get(metric)
        control = measured_scenarios[check["control"]].get(metric)
        if (
            variant is not None
            and control is not None
            and evaluate_direction(check["direction"], variant, control)
        ):
            touched.add(metric)

    return CoverageManifest(
        all_keys=set().union(*measured_scenarios.values()),
        touched_keys=touched,
        priority_params=list(catalog.get("priority_metrics", [])),
        title="Travel-Plan-Permission baseline coverage manifest",
    )


def test_directional_metrics_exist(
    catalog: dict[str, Any], measured_scenarios: dict[str, dict[str, float]]
) -> None:
    missing = {
        (check[side], check["metric"])
        for check in catalog["directionals"]
        for side in ("scenario", "control")
        if check["metric"] not in measured_scenarios[check[side]]
    }
    assert not missing, f"Directional checks reference missing scenario metrics: {sorted(missing)}"


def test_priority_metrics_covered(manifest: CoverageManifest) -> None:
    gaps = manifest.priority_gaps
    assert not gaps, f"Priority metrics with no passing directional check: {gaps}"


def assert_report_current(report_path: Path, generated_report: str) -> None:
    assert report_path.read_text(encoding="utf-8") == generated_report, (
        "Committed baseline coverage report is stale; regenerate it from measured outcomes with "
        "BASELINE_REFRESH_REPORT=1 pytest "
        "tests/baseline/test_coverage_manifest.py::test_generated_baseline_report_detects_drift"
    )


def test_generated_baseline_report_detects_drift(
    catalog: dict[str, Any],
    measured_scenarios: dict[str, dict[str, float]],
    manifest: CoverageManifest,
    record_property: Callable[[str, object], None],
    tmp_path: Path,
) -> None:
    """Keep the committed report aligned with real rule-output variation."""
    rule_flags = {
        key: sorted({outcome[key] for outcome in measured_scenarios.values() if key in outcome})
        for key in sorted(manifest.all_keys)
        if key.startswith("policy.") and key.endswith(".passed")
    }
    assert rule_flags, "The policy adapter emitted no rule flags"
    assert "policy.advance_booking.passed" not in rule_flags
    invalid_flags = {key: values for key, values in rule_flags.items() if values != [0, 1]}
    assert not invalid_flags, f"Policy rule flags need both pass and fail outcomes: {invalid_flags}"
    uncovered_flags = rule_flags.keys() - manifest.touched_keys
    assert (
        not uncovered_flags
    ), f"Rule flags with no passing directional check: {sorted(uncovered_flags)}"

    assert measured_scenarios["late_booking"] == measured_scenarios["base"]

    validation = catalog["validation"]
    compliant = adapter.run_validation_scenario(
        next(s for s in validation["scenarios"] if s["id"] == "validation_base"),
        validation["base"],
    )
    # Three days' notice and a 19-day trip cross both submission thresholds.
    over_limits = adapter.run_validation_scenario(
        {"plan": {"departure_date": "2025-01-04", "return_date": "2025-01-22"}},
        validation["base"],
    )
    expected_controls = {
        "validation.ADV-001.violations": (0, 1),
        "validation.ADV-001.blocking": (0, 1),
        "validation.DUR-001.violations": (0, 1),
        "validation.DUR-001.blocking": (0, 0),
    }
    observed_controls = {key: (compliant[key], over_limits[key]) for key in expected_controls}
    assert observed_controls == expected_controls

    record_property("input", ", ".join(measured_scenarios))
    record_property("observed_rule_flags", str(rule_flags))
    record_property("validation_base_and_over_limits", str(observed_controls))
    generated_report = manifest.to_markdown()
    report_copy = tmp_path / REPORT_PATH.name
    report_copy.write_text(generated_report + "\nStale report content\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="Committed baseline coverage report is stale"):
        assert_report_current(report_copy, generated_report)
    report_copy.write_text(generated_report, encoding="utf-8")
    assert_report_current(report_copy, generated_report)

    if os.environ.get("BASELINE_REFRESH_REPORT") == "1":
        REPORT_PATH.write_text(generated_report, encoding="utf-8")
    assert_report_current(REPORT_PATH, generated_report)
    record_property("report_check", "stale rejected, restored and committed reports matched")
