"""The planner-facing policy snapshot must publish the spend limits TPP enforces.

Observed 2026-09-22 against a local service: BUD-001 (blocking) sets a $5,000 trip limit
and category limits in config/validation.yaml, and a $9,000 trip is blocked on it, yet the
snapshot carried no limits at all. trip-planner therefore showed every cap as $0 or "cannot
be checked", and its printed approval packet said a $1,238 trip was "above the budget cap".
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml

from travel_plan_permission.models import TripPlan
from travel_plan_permission.policy_api import get_policy_snapshot


def _plan() -> TripPlan:
    return TripPlan(
        trip_id="trip-caps",
        traveler_name="Dana Chen",
        destination="Chicago, IL",
        departure_date=date(2026, 10, 5),
        return_date=date(2026, 10, 7),
        purpose="Client review",
        estimated_cost=Decimal("1238"),
    )


def _configured_budget_rule() -> dict[str, object]:
    config = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "config" / "validation.yaml").read_text()
    )
    rules = config["rules"] if isinstance(config, dict) and "rules" in config else config
    return next(rule for rule in rules if rule.get("type") == "budget_limit")


def test_the_snapshot_publishes_the_trip_limit_from_configuration() -> None:
    configured = _configured_budget_rule()
    budget = get_policy_snapshot(_plan()).budget_rules

    assert budget["rule_id"] == configured["code"]
    assert budget["max_trip_total_usd"] == float(configured["trip_limit"])
    assert budget["blocking"] is bool(configured["blocking"])


def test_the_snapshot_publishes_category_limits_from_configuration() -> None:
    configured = _configured_budget_rule()
    budget = get_policy_snapshot(_plan()).budget_rules

    assert budget["category_limits_usd"] == {
        str(category): float(limit) for category, limit in configured["category_limits"].items()
    }


def test_the_limits_reach_the_serialised_http_payload() -> None:
    """The route returns the model as JSON; a field only on the Python object is useless."""

    payload = get_policy_snapshot(_plan()).model_dump(mode="json")
    assert payload["budget_rules"]["max_trip_total_usd"] > 0


def test_the_published_limit_follows_the_configuration(monkeypatch) -> None:
    """A hard-coded 5000 would pass the tests above, because the shipped config says 5000.
    Change the configured limit and the snapshot must change with it."""

    from travel_plan_permission import policy_api
    from travel_plan_permission.validation import BudgetLimitRule, PolicyValidator

    rule = BudgetLimitRule(
        name="test_budget_limit",
        code="BUD-TEST",
        severity="error",
        blocking=True,
        trip_limit=Decimal("1234"),
        category_limits={"lodging": Decimal("600")},
    )
    monkeypatch.setattr(
        policy_api.PolicyValidator,
        "from_runtime_config",
        classmethod(lambda _cls: PolicyValidator([rule])),
    )

    budget = get_policy_snapshot(_plan()).budget_rules
    assert budget == {
        "rule_id": "BUD-TEST",
        "blocking": True,
        "max_trip_total_usd": 1234.0,
        "category_limits_usd": {"lodging": 600.0},
    }


def test_a_policy_with_no_budget_limit_publishes_none(monkeypatch) -> None:
    """Absent means absent: the planner must then say the cap cannot be checked."""

    from travel_plan_permission import policy_api
    from travel_plan_permission.validation import PolicyValidator

    monkeypatch.setattr(
        policy_api.PolicyValidator,
        "from_runtime_config",
        classmethod(lambda _cls: PolicyValidator([])),
    )
    assert get_policy_snapshot(_plan()).budget_rules == {}
