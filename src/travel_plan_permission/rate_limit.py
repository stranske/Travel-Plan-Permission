"""Rate limiting strategy definitions for API consumers."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter

from .security import API_ENDPOINT_PERMISSIONS, Permission


@dataclass(frozen=True)
class RateLimitTier:
    """Immutable rate limit tier definition."""

    name: str
    limit: int
    window_seconds: int


@dataclass(frozen=True)
class RateLimitPolicy:
    """Resolved rate limit policy for a request."""

    limit: int
    window_seconds: int
    tier: str
    scope: str
    reason: str


@dataclass(frozen=True)
class RateLimitEvent:
    """Single rate limit decision logged for monitoring."""

    api_key: str
    endpoint: str
    policy: RateLimitPolicy
    allowed: bool
    remaining: int | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class RateLimitStrategy:
    """Rate limit strategy definition resolved per API key and endpoint."""

    default_tier: RateLimitTier
    tiers_by_permission: dict[Permission, RateLimitTier] = field(default_factory=dict)
    endpoint_overrides: dict[str, RateLimitTier] = field(default_factory=dict)
    api_key_overrides: dict[str, RateLimitTier] = field(default_factory=dict)

    def policy_for(
        self,
        *,
        api_key: str,
        endpoint: str,
        permission: Permission | None = None,
    ) -> RateLimitPolicy:
        """Resolve the rate limit policy for a given API key and endpoint."""

        if api_key in self.api_key_overrides:
            tier = self.api_key_overrides[api_key]
            reason = "api_key_override"
        elif endpoint in self.endpoint_overrides:
            tier = self.endpoint_overrides[endpoint]
            reason = "endpoint_override"
        else:
            resolved_permission = permission or API_ENDPOINT_PERMISSIONS.get(endpoint)
            tier = (
                self.tiers_by_permission.get(resolved_permission, self.default_tier)
                if resolved_permission is not None
                else self.default_tier
            )
            reason = (
                "permission_tier"
                if resolved_permission is not None
                and resolved_permission in self.tiers_by_permission
                else "default_tier"
            )

        return RateLimitPolicy(
            limit=tier.limit,
            window_seconds=tier.window_seconds,
            tier=tier.name,
            scope="api_key",
            reason=reason,
        )

    def bucket_key(self, *, api_key: str, endpoint: str) -> str:
        """Return a stable cache key for rate limit tracking."""

        return f"{api_key}:{endpoint}"


class LazyRateLimitDashboard(Mapping[str, dict[str, int]]):
    """Lazily compute rate limit dashboard widgets."""

    def __init__(self, events: list[RateLimitEvent]) -> None:
        self._events = events
        self._cache: dict[str, dict[str, int]] = {}

    def __getitem__(self, key: str) -> dict[str, int]:
        if key in self._cache:
            return self._cache[key]
        if key == "by_api_key":
            value = self._build_by_api_key()
        elif key == "by_endpoint":
            value = self._build_by_endpoint()
        elif key == "by_tier":
            value = self._build_by_tier()
        elif key == "by_reason":
            value = self._build_by_reason()
        elif key == "by_outcome":
            value = self._build_by_outcome()
        else:
            raise KeyError(key)
        self._cache[key] = value
        return value

    def __iter__(self) -> Iterator[str]:
        return iter(("by_api_key", "by_endpoint", "by_tier", "by_reason", "by_outcome"))

    def __len__(self) -> int:
        return 5

    def materialize(self) -> dict[str, dict[str, int]]:
        """Compute all widgets and return a fully built dashboard."""

        return {key: self[key] for key in self}

    def _build_by_api_key(self) -> dict[str, int]:
        by_api_key: Counter[str] = Counter()
        for event in self._events:
            by_api_key[event.api_key] += 1
        return dict(by_api_key)

    def _build_by_endpoint(self) -> dict[str, int]:
        by_endpoint: Counter[str] = Counter()
        for event in self._events:
            by_endpoint[event.endpoint] += 1
        return dict(by_endpoint)

    def _build_by_tier(self) -> dict[str, int]:
        by_tier: Counter[str] = Counter()
        for event in self._events:
            by_tier[event.policy.tier] += 1
        return dict(by_tier)

    def _build_by_reason(self) -> dict[str, int]:
        by_reason: Counter[str] = Counter()
        for event in self._events:
            by_reason[event.policy.reason] += 1
        return dict(by_reason)

    def _build_by_outcome(self) -> dict[str, int]:
        by_outcome: Counter[str] = Counter()
        for event in self._events:
            by_outcome["allowed" if event.allowed else "blocked"] += 1
        return dict(by_outcome)


def build_rate_limit_dashboard(
    events: list[RateLimitEvent],
    *,
    lazy: bool = True,
) -> Mapping[str, dict[str, int]]:
    """Aggregate rate limit activity for monitoring."""

    if lazy:
        return LazyRateLimitDashboard(events)

    by_api_key: Counter[str] = Counter()
    by_endpoint: Counter[str] = Counter()
    by_tier: Counter[str] = Counter()
    by_reason: Counter[str] = Counter()
    by_outcome: Counter[str] = Counter()

    for event in events:
        by_api_key[event.api_key] += 1
        by_endpoint[event.endpoint] += 1
        by_tier[event.policy.tier] += 1
        by_reason[event.policy.reason] += 1
        by_outcome["allowed" if event.allowed else "blocked"] += 1

    return {
        "by_api_key": dict(by_api_key),
        "by_endpoint": dict(by_endpoint),
        "by_tier": dict(by_tier),
        "by_reason": dict(by_reason),
        "by_outcome": dict(by_outcome),
    }


@dataclass(frozen=True)
class RateLimitDashboardProfile:
    """Performance profile for rate limit dashboard aggregation."""

    event_count: int
    elapsed_seconds: float
    events_per_second: float


def profile_rate_limit_dashboard(
    events: list[RateLimitEvent],
    *,
    timer: Callable[[], float] | None = None,
) -> tuple[Mapping[str, dict[str, int]], RateLimitDashboardProfile]:
    """Profile dashboard aggregation timing and throughput."""

    perf_timer = timer or perf_counter
    start = perf_timer()
    dashboard = build_rate_limit_dashboard(events)
    if isinstance(dashboard, LazyRateLimitDashboard):
        dashboard = dashboard.materialize()
    elapsed = perf_timer() - start
    event_count = len(events)
    throughput = event_count / elapsed if elapsed > 0 else 0.0
    return dashboard, RateLimitDashboardProfile(
        event_count=event_count,
        elapsed_seconds=elapsed,
        events_per_second=throughput,
    )


DEFAULT_RATE_LIMIT_TIERS: dict[str, RateLimitTier] = {
    "standard": RateLimitTier(name="standard", limit=120, window_seconds=60),
    "approval": RateLimitTier(name="approval", limit=60, window_seconds=60),
    "export": RateLimitTier(name="export", limit=30, window_seconds=60),
    "admin": RateLimitTier(name="admin", limit=20, window_seconds=60),
}

DEFAULT_RATE_LIMIT_STRATEGY = RateLimitStrategy(
    default_tier=DEFAULT_RATE_LIMIT_TIERS["standard"],
    tiers_by_permission={
        Permission.VIEW: DEFAULT_RATE_LIMIT_TIERS["standard"],
        Permission.CREATE: DEFAULT_RATE_LIMIT_TIERS["standard"],
        Permission.APPROVE: DEFAULT_RATE_LIMIT_TIERS["approval"],
        Permission.EXPORT: DEFAULT_RATE_LIMIT_TIERS["export"],
        Permission.CONFIGURE: DEFAULT_RATE_LIMIT_TIERS["admin"],
    },
    endpoint_overrides={
        "POST /api/exports/expenses": DEFAULT_RATE_LIMIT_TIERS["export"],
        "GET /api/exports/audit": DEFAULT_RATE_LIMIT_TIERS["export"],
    },
)
