"""Golden and enforced directional coverage for the production submission validator.

Re-bless intentional changes with:
    pytest tests/baseline/test_validation_golden.py --force-regen
Review the resulting CSVs in test_validation_golden/ before committing them.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from baseline_kit import check_metrics, evaluate_direction, load_catalog
from pytest_regressions.num_regression import NumericRegressionFixture

from . import adapter
from .conftest import CATALOG_PATH

_VALIDATION = load_catalog(CATALOG_PATH)["validation"]
_BASE = _VALIDATION["base"]
_SCENARIOS = {s["id"]: s for s in _VALIDATION["scenarios"]}


@pytest.mark.parametrize("scenario", _SCENARIOS.values(), ids=_SCENARIOS)
def test_validation_golden(
    scenario: dict[str, Any], num_regression: NumericRegressionFixture
) -> None:
    check_metrics(num_regression, adapter.run_validation_scenario(scenario, _BASE))


def test_validation_blocking_budget(
    record_property: Callable[[str, object], None],
) -> None:
    directional = next(
        item
        for item in _VALIDATION["directionals"]
        if item["id"] == "validation_blocking_budget"
    )
    assert directional["enforce"] is True
    control = adapter.run_validation_scenario(_SCENARIOS[directional["control"]], _BASE)
    variant = adapter.run_validation_scenario(
        _SCENARIOS[directional["scenario"]], _BASE
    )
    metric = directional["metric"]
    evidence = (
        f"{metric}: over-budget={variant[metric]}, control={control[metric]}; "
        f"blocking totals={variant['validation.n_blocking']}/{control['validation.n_blocking']}"
    )
    record_property("directional", evidence)
    assert control["validation.n_blocking"] == 0, evidence
    assert variant["validation.BUD-001.blocking"] == 1, evidence
    assert variant["validation.n_blocking"] == 1, evidence
    assert evaluate_direction(
        directional["direction"], variant[metric], control[metric]
    ), evidence
