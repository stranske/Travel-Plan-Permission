"""Golden masters of each scenario's flattened approval/policy outcomes.

Re-bless after an intended change:
    pytest tests/baseline/test_golden.py --force-regen
then review and commit the updated baseline CSVs under test_golden/.
"""

from __future__ import annotations

import pytest
from baseline_kit import check_metrics, load_catalog

from . import adapter
from .conftest import CATALOG_PATH

_CATALOG = load_catalog(CATALOG_PATH)
_BASE_REQUEST = _CATALOG["base"]["request"]
_SCENARIOS = _CATALOG["scenarios"]


@pytest.mark.parametrize("scenario", _SCENARIOS, ids=[s["id"] for s in _SCENARIOS])
def test_approval_policy_golden(scenario, num_regression):
    check_metrics(num_regression, adapter.run_scenario(scenario, _BASE_REQUEST))
