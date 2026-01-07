from __future__ import annotations

import pytest

from travel_plan_permission.rate_limit import (
    RateLimitEvent,
    RateLimitPolicy,
    build_rate_limit_dashboard,
    profile_rate_limit_dashboard,
)


def test_rate_limit_dashboard_aggregates_counts() -> None:
    policy_standard = RateLimitPolicy(
        limit=120,
        window_seconds=60,
        tier="standard",
        scope="api_key",
        reason="default_tier",
    )
    policy_export = RateLimitPolicy(
        limit=30,
        window_seconds=60,
        tier="export",
        scope="api_key",
        reason="endpoint_override",
    )

    events = [
        RateLimitEvent(
            api_key="key-1",
            endpoint="GET /api/itineraries",
            policy=policy_standard,
            allowed=True,
        ),
        RateLimitEvent(
            api_key="key-1",
            endpoint="GET /api/itineraries",
            policy=policy_standard,
            allowed=False,
        ),
        RateLimitEvent(
            api_key="key-2",
            endpoint="POST /api/exports/expenses",
            policy=policy_export,
            allowed=True,
        ),
    ]

    dashboard = build_rate_limit_dashboard(events)

    assert dashboard["by_api_key"]["key-1"] == 2
    assert dashboard["by_api_key"]["key-2"] == 1
    assert dashboard["by_endpoint"]["GET /api/itineraries"] == 2
    assert dashboard["by_endpoint"]["POST /api/exports/expenses"] == 1
    assert dashboard["by_tier"]["standard"] == 2
    assert dashboard["by_tier"]["export"] == 1
    assert dashboard["by_reason"]["default_tier"] == 2
    assert dashboard["by_reason"]["endpoint_override"] == 1
    assert dashboard["by_outcome"]["allowed"] == 2
    assert dashboard["by_outcome"]["blocked"] == 1


def test_rate_limit_dashboard_profile_records_timing() -> None:
    policy_standard = RateLimitPolicy(
        limit=120,
        window_seconds=60,
        tier="standard",
        scope="api_key",
        reason="default_tier",
    )

    events = [
        RateLimitEvent(
            api_key="key-1",
            endpoint="GET /api/itineraries",
            policy=policy_standard,
            allowed=True,
        ),
        RateLimitEvent(
            api_key="key-2",
            endpoint="GET /api/itineraries",
            policy=policy_standard,
            allowed=False,
        ),
    ]

    timestamps = iter([10.0, 10.25])

    def _fake_timer() -> float:
        return next(timestamps)

    dashboard, profile = profile_rate_limit_dashboard(events, timer=_fake_timer)

    assert dashboard["by_tier"]["standard"] == 2
    assert dashboard["by_outcome"]["blocked"] == 1
    assert profile.event_count == 2
    assert profile.elapsed_seconds == pytest.approx(0.25)
    assert profile.events_per_second == pytest.approx(8.0)
