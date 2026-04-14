from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from travel_plan_permission.planner_auth import (
    PlannerAuthConfig,
    PlannerAuthMode,
    authenticate_request,
    mint_bootstrap_token,
)
from travel_plan_permission.security import Permission


def _set_bootstrap_env(monkeypatch) -> None:
    monkeypatch.setenv("TPP_BASE_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("TPP_OIDC_PROVIDER", "google")
    monkeypatch.setenv("TPP_AUTH_MODE", "bootstrap-token")
    monkeypatch.setenv("TPP_BOOTSTRAP_SIGNING_SECRET", "bootstrap-secret-123")


def test_bootstrap_auth_config_requires_explicit_mode(monkeypatch) -> None:
    monkeypatch.setenv("TPP_BASE_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("TPP_OIDC_PROVIDER", "google")
    config = PlannerAuthConfig.from_env()

    assert config.auth_mode is None
    assert config.missing_config == ("TPP_AUTH_MODE",)


def test_bootstrap_token_authenticates_required_permission(monkeypatch) -> None:
    _set_bootstrap_env(monkeypatch)
    now = datetime(2026, 4, 14, 7, 0, tzinfo=UTC)
    token = mint_bootstrap_token(
        subject="planner-preview",
        permissions=(Permission.VIEW, Permission.CREATE),
        provider="google",
        secret="bootstrap-secret-123",
        expires_in_seconds=600,
        now=now,
    )

    context = authenticate_request(
        f"Bearer {token}",
        config=PlannerAuthConfig.from_env(),
        required_permission=Permission.CREATE,
        now=now + timedelta(seconds=60),
    )

    assert context.auth_mode == PlannerAuthMode.BOOTSTRAP_TOKEN
    assert context.subject == "planner-preview"
    assert context.can(Permission.VIEW)
    assert context.can(Permission.CREATE)


def test_bootstrap_token_rejects_missing_permission(monkeypatch) -> None:
    _set_bootstrap_env(monkeypatch)
    token = mint_bootstrap_token(
        subject="planner-preview",
        permissions=(Permission.VIEW,),
        provider="google",
        secret="bootstrap-secret-123",
        expires_in_seconds=600,
    )

    with pytest.raises(PermissionError, match="does not grant 'create'"):
        authenticate_request(
            f"Bearer {token}",
            config=PlannerAuthConfig.from_env(),
            required_permission=Permission.CREATE,
        )


def test_bootstrap_token_rejects_expired_token(monkeypatch) -> None:
    _set_bootstrap_env(monkeypatch)
    issued_at = datetime(2026, 4, 14, 7, 0, tzinfo=UTC)
    token = mint_bootstrap_token(
        subject="planner-preview",
        permissions=(Permission.VIEW, Permission.CREATE),
        provider="google",
        secret="bootstrap-secret-123",
        expires_in_seconds=30,
        now=issued_at,
    )

    with pytest.raises(PermissionError, match="has expired"):
        authenticate_request(
            f"Bearer {token}",
            config=PlannerAuthConfig.from_env(),
            required_permission=Permission.VIEW,
            now=issued_at + timedelta(seconds=45),
        )
