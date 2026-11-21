"""Coverage manifest -- which flat metric keys are exercised; emit a report.

Uses the generic ``baseline_kit.CoverageManifest``. The app supplies the input
space (every flat metric key the surface produces across all scenarios) and the
touched set (metric keys referenced by at least one directional check).
"""

from __future__ import annotations

import os
from pathlib import Path

from baseline_kit import CoverageManifest, load_catalog

from . import adapter
from .conftest import CATALOG_PATH, REPO_ROOT

REPORT_PATH = REPO_ROOT / "docs" / "reports" / "baseline-coverage.md"


def _all_metric_keys(catalog) -> set[str]:
    base_request = catalog["base"]["request"]
    keys: set[str] = set()
    for scenario in catalog["scenarios"]:
        keys.update(adapter.run_scenario(scenario, base_request).keys())
    return keys


def _measured_scenarios(catalog) -> dict[str, dict[str, float]]:
    """Evaluate each catalog input through the supported adapter entry point."""
    base_request = catalog["base"]["request"]
    return {
        scenario["id"]: adapter.run_scenario(scenario, base_request)
        for scenario in catalog["scenarios"]
    }


def _build_manifest() -> CoverageManifest:
    catalog = load_catalog(CATALOG_PATH)
    touched = {d["metric"] for d in catalog.get("directionals", [])}
    return CoverageManifest(
        all_keys=_all_metric_keys(catalog),
        touched_keys=touched,
        priority_params=list(catalog.get("priority_metrics", [])),
        title="Travel-Plan-Permission baseline coverage manifest",
    )


def test_directional_metrics_exist():
    m = _build_manifest()
    assert not m.unknown_catalog_keys, (
        "Directional checks reference metric keys the adapter never produces: "
        f"{sorted(m.unknown_catalog_keys)}"
    )


def test_priority_metrics_covered():
    m = _build_manifest()
    assert not m.priority_gaps, "Priority metrics with no directional check: " + ", ".join(
        m.priority_gaps
    )


def test_emit_coverage_report(tmp_path: Path):
    m = _build_manifest()
    report_path = (
        REPORT_PATH
        if os.environ.get("BASELINE_REFRESH_REPORT") == "1"
        else tmp_path / "baseline-coverage.md"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(m.to_markdown())
    assert report_path.exists()


def test_generated_baseline_report_detects_drift(record_property):
    """Keep the committed report aligned with real rule-output variation."""
    catalog = load_catalog(CATALOG_PATH)
    measured = _measured_scenarios(catalog)
    generated_report = _build_manifest().to_markdown()
    rule_flags = sorted(key for key in _all_metric_keys(catalog) if key.endswith(".passed"))

    non_varying = {
        key: sorted({outcome[key] for outcome in measured.values()})
        for key in rule_flags
        if len({outcome[key] for outcome in measured.values()}) == 1
    }
    assert not non_varying, (
        "Policy rule flags need measured pass/fail fixtures; unchanged flags: "
        f"{non_varying}"
    )

    # Advance-booking and duration remain on the production validation surface;
    # this policy-lite manifest must not recreate either compatibility control.
    validation_base = catalog["validation"]["base"]
    validation_metrics = adapter.run_validation_scenario(
        catalog["validation"]["scenarios"][0], validation_base
    )
    assert validation_metrics["validation.ADV-001.violations"] == 0
    assert validation_metrics["validation.DUR-001.violations"] == 0
    assert not {"policy.ADV-001.passed", "policy.DUR-001.passed"} & set(rule_flags)

    record_property("input", "all catalog scenarios through adapter.run_scenario")
    record_property("observed_rule_flags", str({key: sorted({row[key] for row in measured.values()}) for key in rule_flags}))
    record_property("compatibility_control", "ADV-001 and DUR-001 remain zero on validation_base")
    if os.environ.get("BASELINE_REFRESH_REPORT") == "1":
        REPORT_PATH.write_text(generated_report)
    assert REPORT_PATH.read_text() == generated_report, (
        "Committed baseline coverage report is stale; regenerate it from measured outcomes with "
        "BASELINE_REFRESH_REPORT=1 pytest "
        "tests/baseline/test_coverage_manifest.py::test_generated_baseline_report_detects_drift"
    )
