"""Rate limiting strategy definitions for API consumers."""

from __future__ import annotations

from dataclasses import dataclass, field

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
            tier = self.tiers_by_permission.get(resolved_permission, self.default_tier)
            reason = (
                "permission_tier"
                if resolved_permission in self.tiers_by_permission
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
