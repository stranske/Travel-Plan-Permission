from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

import travel_plan_permission.planner_auth as planner_auth
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


def _set_oidc_env(monkeypatch) -> None:
    monkeypatch.setenv("TPP_BASE_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("TPP_OIDC_PROVIDER", "google")
    monkeypatch.setenv("TPP_AUTH_MODE", "oidc")
    monkeypatch.setenv("TPP_OIDC_AUDIENCE", "trip-planner")
    monkeypatch.setenv("TPP_OIDC_ISSUER", "https://accounts.google.com")
    monkeypatch.setenv("TPP_OIDC_JWKS_URL", "https://issuer.example/jwks.json")


def _rsa_jwk(private_key, *, kid: str) -> dict[str, object]:
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk["kid"] = kid
    jwk["alg"] = "RS256"
    jwk["use"] = "sig"
    return jwk


def _oidc_token(
    private_key,
    *,
    kid: str = "planner-key",
    subject: str = "user@example.com",
    audience: str = "trip-planner",
    issuer: str = "https://accounts.google.com",
    expires_delta: timedelta = timedelta(minutes=10),
    include_nbf: bool = True,
    nbf_offset: timedelta = timedelta(seconds=-5),
) -> str:
    now = datetime.now(UTC)
    claims = {
        "iss": issuer,
        "aud": audience,
        "sub": subject,
        "exp": now + expires_delta,
    }
    if include_nbf:
        claims["nbf"] = now + nbf_offset
    return jwt.encode(
        claims,
        private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )


@pytest.fixture
def oidc_keys(monkeypatch):
    planner_auth._JWKS_CACHE.clear()
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwks = {"keys": [_rsa_jwk(private_key, kid="planner-key")]}
    monkeypatch.setattr(planner_auth, "_fetch_jwks_document", lambda _url: jwks)
    return private_key


def test_bootstrap_auth_config_requires_explicit_mode(monkeypatch) -> None:
    monkeypatch.setenv("TPP_BASE_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("TPP_OIDC_PROVIDER", "google")
    config = PlannerAuthConfig.from_env()

    assert config.auth_mode is None
    assert config.missing_config == ("TPP_AUTH_MODE",)


def test_oidc_auth_config_requires_audience(monkeypatch) -> None:
    monkeypatch.setenv("TPP_BASE_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("TPP_OIDC_PROVIDER", "google")
    monkeypatch.setenv("TPP_AUTH_MODE", "oidc")

    config = PlannerAuthConfig.from_env()

    assert config.auth_mode == PlannerAuthMode.OIDC
    assert config.missing_config == ("TPP_OIDC_AUDIENCE",)


def test_oidc_token_authenticates_default_traveler_role(monkeypatch, oidc_keys) -> None:
    _set_oidc_env(monkeypatch)
    token = _oidc_token(oidc_keys)

    context = authenticate_request(
        f"Bearer {token}",
        config=PlannerAuthConfig.from_env(),
        required_permission=Permission.CREATE,
    )

    assert context.auth_mode == PlannerAuthMode.OIDC
    assert context.subject == "user@example.com"
    assert context.provider == "google"
    assert context.can(Permission.VIEW)
    assert context.can(Permission.CREATE)


def test_oidc_token_uses_role_mapping(monkeypatch, oidc_keys) -> None:
    _set_oidc_env(monkeypatch)
    monkeypatch.setenv("TPP_OIDC_ROLE_MAP", '{"sub:user@example.com": "finance_admin"}')
    token = _oidc_token(oidc_keys)

    context = authenticate_request(
        f"Bearer {token}",
        config=PlannerAuthConfig.from_env(),
        required_permission=Permission.EXPORT,
    )

    assert context.can(Permission.EXPORT)


@pytest.mark.parametrize(
    ("token_kwargs", "message"),
    [
        ({"expires_delta": timedelta(seconds=-30)}, "has expired"),
        ({"audience": "wrong-audience"}, "audience is invalid"),
        ({"issuer": "https://issuer.example"}, "issuer is invalid"),
    ],
)
def test_oidc_token_rejects_invalid_standard_claims(
    monkeypatch,
    oidc_keys,
    token_kwargs,
    message,
) -> None:
    _set_oidc_env(monkeypatch)
    token = _oidc_token(oidc_keys, **token_kwargs)

    with pytest.raises(PermissionError, match=message):
        authenticate_request(
            f"Bearer {token}",
            config=PlannerAuthConfig.from_env(),
            required_permission=Permission.VIEW,
        )


def test_oidc_token_rejects_missing_jwks_key_id(monkeypatch, oidc_keys) -> None:
    _set_oidc_env(monkeypatch)
    token = _oidc_token(oidc_keys, kid="missing-key")

    with pytest.raises(PermissionError, match="key id was not found"):
        authenticate_request(
            f"Bearer {token}",
            config=PlannerAuthConfig.from_env(),
            required_permission=Permission.VIEW,
        )


def test_oidc_token_rejects_signature_mismatch(monkeypatch, oidc_keys) -> None:
    _set_oidc_env(monkeypatch)
    assert oidc_keys is not None
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = _oidc_token(other_key)

    with pytest.raises(PermissionError, match="is invalid"):
        authenticate_request(
            f"Bearer {token}",
            config=PlannerAuthConfig.from_env(),
            required_permission=Permission.VIEW,
        )


def test_oidc_token_rejects_missing_nbf(monkeypatch, oidc_keys) -> None:
    _set_oidc_env(monkeypatch)
    token = _oidc_token(oidc_keys, include_nbf=False)

    with pytest.raises(PermissionError, match="is invalid"):
        authenticate_request(
            f"Bearer {token}",
            config=PlannerAuthConfig.from_env(),
            required_permission=Permission.VIEW,
        )


def test_oidc_token_rejects_not_yet_valid_nbf(monkeypatch, oidc_keys) -> None:
    _set_oidc_env(monkeypatch)
    token = _oidc_token(oidc_keys, nbf_offset=timedelta(minutes=2))

    with pytest.raises(PermissionError, match="is invalid"):
        authenticate_request(
            f"Bearer {token}",
            config=PlannerAuthConfig.from_env(),
            required_permission=Permission.VIEW,
        )


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
