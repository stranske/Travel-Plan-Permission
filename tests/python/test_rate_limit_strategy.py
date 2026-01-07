from __future__ import annotations

from travel_plan_permission.rate_limit import (
    DEFAULT_RATE_LIMIT_STRATEGY,
    DEFAULT_RATE_LIMIT_TIERS,
    RateLimitStrategy,
)
from travel_plan_permission.security import Permission


def test_default_strategy_uses_permission_tiers() -> None:
    policy = DEFAULT_RATE_LIMIT_STRATEGY.policy_for(
        api_key="test-key",
        endpoint="GET /api/itineraries",
    )

    assert policy.limit == DEFAULT_RATE_LIMIT_TIERS["standard"].limit
    assert policy.window_seconds == DEFAULT_RATE_LIMIT_TIERS["standard"].window_seconds
    assert policy.tier == "standard"
    assert policy.reason == "permission_tier"
    assert policy.scope == "api_key"


def test_endpoint_override_takes_precedence() -> None:
    strategy = RateLimitStrategy(
        default_tier=DEFAULT_RATE_LIMIT_TIERS["standard"],
        tiers_by_permission={Permission.VIEW: DEFAULT_RATE_LIMIT_TIERS["standard"]},
        endpoint_overrides={"GET /api/itineraries": DEFAULT_RATE_LIMIT_TIERS["export"]},
    )

    policy = strategy.policy_for(api_key="test-key", endpoint="GET /api/itineraries")

    assert policy.tier == "export"
    assert policy.reason == "endpoint_override"


def test_api_key_override_takes_precedence() -> None:
    strategy = RateLimitStrategy(
        default_tier=DEFAULT_RATE_LIMIT_TIERS["standard"],
        endpoint_overrides={"GET /api/itineraries": DEFAULT_RATE_LIMIT_TIERS["export"]},
        api_key_overrides={"vip-key": DEFAULT_RATE_LIMIT_TIERS["approval"]},
    )

    policy = strategy.policy_for(api_key="vip-key", endpoint="GET /api/itineraries")

    assert policy.tier == "approval"
    assert policy.reason == "api_key_override"


def test_default_tier_applies_for_unknown_endpoints() -> None:
    strategy = RateLimitStrategy(default_tier=DEFAULT_RATE_LIMIT_TIERS["standard"])

    policy = strategy.policy_for(api_key="test-key", endpoint="GET /api/unknown")

    assert policy.tier == "standard"
    assert policy.reason == "default_tier"
