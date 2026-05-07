from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

import travel_plan_permission.planner_auth as planner_auth
from travel_plan_permission.planner_auth import (
    AuthMode,
    OIDCAuthenticationError,
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
    audience: str | None = "trip-planner",
    issuer: str | None = "https://accounts.google.com",
    expires_delta: timedelta = timedelta(minutes=10),
    include_nbf: bool = True,
    nbf_offset: timedelta = timedelta(seconds=-5),
) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": subject,
        "exp": now + expires_delta,
    }
    if issuer is not None:
        claims["iss"] = issuer
    if audience is not None:
        claims["aud"] = audience
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


def test_auth_mode_alias_includes_oidc() -> None:
    assert AuthMode.OIDC.value == "oidc"
    assert PlannerAuthMode is AuthMode


def test_oidc_auth_config_requires_audience(monkeypatch) -> None:
    monkeypatch.setenv("TPP_BASE_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("TPP_OIDC_PROVIDER", "google")
    monkeypatch.setenv("TPP_AUTH_MODE", "oidc")

    config = PlannerAuthConfig.from_env()

    assert config.auth_mode == PlannerAuthMode.OIDC
    assert config.missing_config == ("TPP_OIDC_AUDIENCE",)


@pytest.mark.parametrize(
    ("provider", "requires_override"), [("azure_ad", True), ("okta", True), ("google", False)]
)
def test_oidc_provider_registry_defaults(provider, requires_override) -> None:
    config = PlannerAuthConfig(
        base_url="http://127.0.0.1:8000",
        oidc_provider=provider,
        auth_mode=PlannerAuthMode.OIDC,
        access_token_configured=False,
        bootstrap_secret_configured=False,
        bootstrap_ttl_seconds=900,
        oidc_audience="trip-planner",
        oidc_role_map_configured=False,
        oidc_role_map={},
        oidc_subject_claim="sub",
        missing_config=(),
        invalid_config=(),
    )

    if requires_override:
        with pytest.raises(ValueError, match="requires TPP_OIDC_ISSUER and TPP_OIDC_JWKS_URL"):
            planner_auth._oidc_provider_settings(config)
    else:
        settings = planner_auth._oidc_provider_settings(config)
        assert settings == {
            "issuer": "https://accounts.google.com",
            "jwks_url": "https://www.googleapis.com/oauth2/v3/certs",
        }

    # Explicit values should always bypass placeholder defaults.
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("TPP_OIDC_ISSUER", "https://issuer.example")
        monkeypatch.setenv("TPP_OIDC_JWKS_URL", "https://issuer.example/jwks.json")
        settings = planner_auth._oidc_provider_settings(config)

    assert settings == {
        "issuer": "https://issuer.example",
        "jwks_url": "https://issuer.example/jwks.json",
    }


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


def test_oidc_token_uses_custom_subject_claim_for_role_mapping(monkeypatch, oidc_keys) -> None:
    _set_oidc_env(monkeypatch)
    monkeypatch.setenv("TPP_OIDC_SUBJECT_CLAIM", "email")
    monkeypatch.setenv("TPP_OIDC_ROLE_MAP", '{"email:user@example.com": "finance_admin"}')
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "opaque-subject",
            "email": "user@example.com",
            "iss": "https://accounts.google.com",
            "aud": "trip-planner",
            "nbf": now - timedelta(seconds=5),
            "exp": now + timedelta(minutes=10),
        },
        oidc_keys,
        algorithm="RS256",
        headers={"kid": "planner-key"},
    )

    context = authenticate_request(
        f"Bearer {token}",
        config=PlannerAuthConfig.from_env(),
        required_permission=Permission.EXPORT,
    )

    assert context.subject == "user@example.com"
    assert context.can(Permission.EXPORT)


def test_oidc_token_uses_role_mapping_file(monkeypatch, tmp_path, oidc_keys) -> None:
    _set_oidc_env(monkeypatch)
    role_map_file = tmp_path / "oidc-role-map.json"
    role_map_file.write_text('{"sub:user@example.com": "finance_admin"}', encoding="utf-8")
    monkeypatch.setenv("TPP_OIDC_ROLE_MAP_FILE", str(role_map_file))
    config = PlannerAuthConfig.from_env()
    role_map_file.write_text('{"sub:user@example.com": "traveler"}', encoding="utf-8")
    token = _oidc_token(oidc_keys)

    context = authenticate_request(
        f"Bearer {token}",
        config=config,
        required_permission=Permission.EXPORT,
    )

    assert config.oidc_role_map_configured is True
    assert context.can(Permission.EXPORT)


def test_oidc_auth_config_rejects_missing_role_map_file(monkeypatch, tmp_path) -> None:
    _set_oidc_env(monkeypatch)
    monkeypatch.setenv("TPP_OIDC_ROLE_MAP_FILE", str(tmp_path / "missing-role-map.json"))

    config = PlannerAuthConfig.from_env()

    assert config.invalid_config == ("TPP_OIDC_ROLE_MAP_FILE",)
    assert config.oidc_role_map == {}


def test_oidc_auth_config_rejects_invalid_role_map_file_json(monkeypatch, tmp_path) -> None:
    _set_oidc_env(monkeypatch)
    role_map_file = tmp_path / "oidc-role-map.json"
    role_map_file.write_text("{not-json", encoding="utf-8")
    monkeypatch.setenv("TPP_OIDC_ROLE_MAP_FILE", str(role_map_file))

    config = PlannerAuthConfig.from_env()

    assert config.invalid_config == ("TPP_OIDC_ROLE_MAP_FILE",)
    assert config.oidc_role_map == {}


def test_oidc_auth_config_rejects_non_object_role_map_file(monkeypatch, tmp_path) -> None:
    _set_oidc_env(monkeypatch)
    role_map_file = tmp_path / "oidc-role-map.json"
    role_map_file.write_text('["finance_admin"]', encoding="utf-8")
    monkeypatch.setenv("TPP_OIDC_ROLE_MAP_FILE", str(role_map_file))

    config = PlannerAuthConfig.from_env()

    assert config.invalid_config == ("TPP_OIDC_ROLE_MAP_FILE",)
    assert config.oidc_role_map == {}


def test_oidc_auth_config_rejects_conflicting_role_map_sources(monkeypatch, tmp_path) -> None:
    _set_oidc_env(monkeypatch)
    role_map_file = tmp_path / "oidc-role-map.json"
    role_map_file.write_text('{"sub:user@example.com": "finance_admin"}', encoding="utf-8")
    monkeypatch.setenv("TPP_OIDC_ROLE_MAP", '{"sub:user@example.com": "traveler"}')
    monkeypatch.setenv("TPP_OIDC_ROLE_MAP_FILE", str(role_map_file))

    config = PlannerAuthConfig.from_env()

    assert config.invalid_config == ("TPP_OIDC_ROLE_MAP", "TPP_OIDC_ROLE_MAP_FILE")


@pytest.mark.parametrize(
    ("token_kwargs", "message"),
    [
        ({"expires_delta": timedelta(seconds=-30)}, "has expired"),
        ({"audience": "wrong-audience"}, "audience is invalid"),
        ({"issuer": "https://issuer.example"}, "issuer is invalid"),
        ({"audience": None}, "is invalid"),
        ({"issuer": None}, "is invalid"),
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


@pytest.mark.parametrize(
    ("token_kwargs", "expected_message"),
    [
        ({"expires_delta": timedelta(seconds=-30)}, "has expired"),
        ({"audience": "wrong-audience"}, "audience is invalid"),
        ({"issuer": "https://issuer.example"}, "issuer is invalid"),
    ],
)
def test_oidc_standard_claim_failures_raise_structured_invalid_token(
    monkeypatch,
    oidc_keys,
    token_kwargs,
    expected_message,
) -> None:
    _set_oidc_env(monkeypatch)
    token = _oidc_token(oidc_keys, **token_kwargs)

    with pytest.raises(OIDCAuthenticationError, match=expected_message) as excinfo:
        authenticate_request(
            f"Bearer {token}",
            config=PlannerAuthConfig.from_env(),
            required_permission=Permission.VIEW,
        )

    assert excinfo.value.error_code == "invalid_token"


def test_oidc_kid_miss_raises_structured_invalid_token(monkeypatch, oidc_keys) -> None:
    _set_oidc_env(monkeypatch)
    token = _oidc_token(oidc_keys, kid="missing-key")

    with pytest.raises(OIDCAuthenticationError, match="key id was not found") as excinfo:
        authenticate_request(
            f"Bearer {token}",
            config=PlannerAuthConfig.from_env(),
            required_permission=Permission.VIEW,
        )

    assert excinfo.value.error_code == "invalid_token"


def test_oidc_signature_mismatch_raises_structured_invalid_token(monkeypatch, oidc_keys) -> None:
    _set_oidc_env(monkeypatch)
    assert oidc_keys is not None
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = _oidc_token(other_key)

    with pytest.raises(OIDCAuthenticationError, match="is invalid") as excinfo:
        authenticate_request(
            f"Bearer {token}",
            config=PlannerAuthConfig.from_env(),
            required_permission=Permission.VIEW,
        )

    assert excinfo.value.error_code == "invalid_token"


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


def test_jwks_cache_reuses_document_within_ttl(monkeypatch) -> None:
    planner_auth._JWKS_CACHE.clear()
    fetch_calls: list[str] = []
    document = {"keys": [{"kid": "one"}]}

    monkeypatch.setattr(planner_auth.time, "monotonic", lambda: 100.0)

    def _fetch(url: str) -> dict[str, object]:
        fetch_calls.append(url)
        return document

    monkeypatch.setattr(planner_auth, "_fetch_jwks_document", _fetch)

    first = planner_auth._get_cached_jwks("https://issuer.example/jwks.json")
    second = planner_auth._get_cached_jwks("https://issuer.example/jwks.json")

    assert first == document
    assert second == document
    assert fetch_calls == ["https://issuer.example/jwks.json"]


def test_jwks_cache_refreshes_after_ttl_expiry(monkeypatch) -> None:
    planner_auth._JWKS_CACHE.clear()
    ticks = iter([100.0, 100.0, 750.0, 750.0])
    fetch_counter = {"value": 0}

    monkeypatch.setattr(planner_auth.time, "monotonic", lambda: next(ticks))

    def _fetch(_url: str) -> dict[str, object]:
        fetch_counter["value"] += 1
        return {"keys": [{"kid": f"k{fetch_counter['value']}"}]}

    monkeypatch.setattr(planner_auth, "_fetch_jwks_document", _fetch)

    first = planner_auth._get_cached_jwks("https://issuer.example/jwks.json")
    second = planner_auth._get_cached_jwks("https://issuer.example/jwks.json")

    assert first["keys"][0]["kid"] == "k1"
    assert second["keys"][0]["kid"] == "k2"
    assert fetch_counter["value"] == 2


def test_jwks_cache_force_refresh_bypasses_ttl(monkeypatch) -> None:
    planner_auth._JWKS_CACHE.clear()
    fetch_counter = {"value": 0}

    monkeypatch.setattr(planner_auth.time, "monotonic", lambda: 100.0)

    def _fetch(_url: str) -> dict[str, object]:
        fetch_counter["value"] += 1
        return {"keys": [{"kid": f"k{fetch_counter['value']}"}]}

    monkeypatch.setattr(planner_auth, "_fetch_jwks_document", _fetch)

    first = planner_auth._get_cached_jwks("https://issuer.example/jwks.json")
    second = planner_auth._get_cached_jwks(
        "https://issuer.example/jwks.json",
        force_refresh=True,
    )

    assert first["keys"][0]["kid"] == "k1"
    assert second["keys"][0]["kid"] == "k2"
    assert fetch_counter["value"] == 2


def test_oidc_kid_miss_forces_jwks_refresh(monkeypatch) -> None:
    _set_oidc_env(monkeypatch)
    planner_auth._JWKS_CACHE.clear()

    signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = _oidc_token(signing_key, kid="rotated")

    stale_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    fresh_jwks = {"keys": [_rsa_jwk(signing_key, kid="rotated")]}
    stale_jwks = {"keys": [_rsa_jwk(stale_key, kid="stale")]}
    fetch_counter = {"value": 0}

    def _fetch(_url: str) -> dict[str, object]:
        fetch_counter["value"] += 1
        if fetch_counter["value"] == 1:
            return stale_jwks
        return fresh_jwks

    monkeypatch.setattr(planner_auth, "_fetch_jwks_document", _fetch)

    context = authenticate_request(
        f"Bearer {token}",
        config=PlannerAuthConfig.from_env(),
        required_permission=Permission.VIEW,
    )

    assert context.subject == "user@example.com"
    assert fetch_counter["value"] == 2


@pytest.mark.integration
def test_oidc_token_authenticates_against_stubbed_jwks_transport(monkeypatch) -> None:
    _set_oidc_env(monkeypatch)
    planner_auth._JWKS_CACHE.clear()
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = _oidc_token(private_key)
    jwks = {"keys": [_rsa_jwk(private_key, kid="planner-key")]}

    def _fake_get(url: str, *, timeout: float) -> httpx.Response:
        assert timeout == 5.0
        request = httpx.Request("GET", url)
        return httpx.Response(200, json=jwks, request=request)

    monkeypatch.setenv("TPP_OIDC_JWKS_URL", "https://issuer.example/jwks.json")
    monkeypatch.setattr(planner_auth.httpx, "get", _fake_get)
    context = authenticate_request(
        f"Bearer {token}",
        config=PlannerAuthConfig.from_env(),
        required_permission=Permission.VIEW,
    )

    assert context.subject == "user@example.com"
    assert context.auth_mode == PlannerAuthMode.OIDC
    cached = planner_auth._get_cached_jwks("https://issuer.example/jwks.json")
    assert cached == jwks


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
