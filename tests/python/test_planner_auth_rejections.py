"""The paths `planner_auth` takes when it says NO, and the codes it reports when it does.

`planner_auth.py` is the lowest-covered file in this repository at 80.5%, and the 67 unexercised
statements are concentrated in its refusals: a malformed token, an unsupported version, a BAD
SIGNATURE, an unreadable payload, and the misconfiguration checks in `from_env`.

Those are the paths that stop a forged or stale token. Every one of them raises, so a defect there
does not surface as an error — it surfaces as a token being accepted, which nothing else in the
suite would notice.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

import travel_plan_permission.planner_auth as planner_auth
from travel_plan_permission.planner_auth import Permission, PlannerAuthMode

SECRET = "a-secret-long-enough-to-pass-the-minimum"
OTHER_SECRET = "a-different-secret-also-long-enough-xx"


def _token(**overrides) -> str:
    kwargs = {
        "subject": "planner@example.com",
        "permissions": (Permission.VIEW,),
        "provider": "azure_ad",
        "secret": SECRET,
        "expires_in_seconds": 300,
        "now": datetime.now(UTC),
    }
    kwargs.update(overrides)
    return planner_auth.mint_bootstrap_token(**kwargs)


# ---------------------------------------------------------------------------------------------
# Token rejection. Each of these is a way a token can be wrong, and each must be refused.
# ---------------------------------------------------------------------------------------------


def test_a_freshly_minted_token_is_accepted():
    """The control. Without it, a parser that rejected EVERYTHING would pass every test below."""
    claims = planner_auth._parse_bootstrap_token(_token(), secret=SECRET)
    assert claims.sub == "planner@example.com"
    assert claims.provider == "azure_ad"


@pytest.mark.parametrize(
    "malformed",
    ["", "not-a-token", "only.two", "a.b.c.d", "....."],
)
def test_a_token_that_is_not_three_parts_is_refused(malformed):
    with pytest.raises(ValueError, match="Malformed bootstrap token"):
        planner_auth._parse_bootstrap_token(malformed, secret=SECRET)


def test_a_token_from_an_unsupported_version_is_refused():
    """A version bump must invalidate old tokens rather than parse them under new rules."""
    good = _token()
    _, payload, signature = good.split(".")
    with pytest.raises(ValueError, match="Unsupported bootstrap token version"):
        planner_auth._parse_bootstrap_token(f"tppv0.{payload}.{signature}", secret=SECRET)


def test_a_token_signed_with_another_secret_is_refused():
    """THE ONE THAT MATTERS. If this branch stopped raising, any party able to construct a payload
    could mint a token this service accepts — and nothing else in the suite would notice, because
    the token would simply work."""
    forged = _token(secret=OTHER_SECRET)
    with pytest.raises(ValueError, match="Invalid bootstrap token signature"):
        planner_auth._parse_bootstrap_token(forged, secret=SECRET)


def test_a_tampered_payload_is_refused():
    """Editing the claims invalidates the signature, which is the entire point of signing them."""
    good = _token()
    version, payload, signature = good.split(".")
    decoded = json.loads(planner_auth._b64url_decode(payload))
    decoded["sub"] = "someone-else@example.com"
    tampered = planner_auth._b64url_encode(json.dumps(decoded).encode("utf-8"))
    with pytest.raises(ValueError, match="Invalid bootstrap token signature"):
        planner_auth._parse_bootstrap_token(f"{version}.{tampered}.{signature}", secret=SECRET)


def test_a_correctly_signed_but_unreadable_payload_is_refused():
    """Signature valid, contents nonsense — refused for the payload, not mistaken for a good token.

    Reached by signing garbage with the real secret, so this exercises the payload branch rather
    than the signature branch above it.
    """
    garbage = planner_auth._b64url_encode(b"{not json")
    import hashlib
    import hmac

    signature = hmac.new(SECRET.encode("utf-8"), garbage.encode("utf-8"), hashlib.sha256).digest()
    token = f"{planner_auth._TOKEN_VERSION}.{garbage}.{planner_auth._b64url_encode(signature)}"
    with pytest.raises(ValueError, match="Malformed bootstrap token payload"):
        planner_auth._parse_bootstrap_token(token, secret=SECRET)


# ---------------------------------------------------------------------------------------------
# Failure codes. These are what an operator reads when authentication is refused.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message, expected",
    [
        ("Planner auth is not ready", "config.not_ready"),
        ("Unsupported auth mode", "config.unsupported_mode"),
        ("something else entirely", "config.error"),
    ],
)
def test_configuration_errors_map_to_distinct_codes(message, expected):
    """Three configuration faults with three different fixes; one shared code would hide two."""
    assert planner_auth._failure_reason_code(ValueError(message)) == expected


@pytest.mark.parametrize(
    "message, expected",
    [
        ("Missing bearer token", "auth.missing_bearer"),
        ("Token expired", "auth.expired"),
        ("Wrong audience for this token", "auth.bad_audience"),
        ("Unknown provider in token", "auth.bad_provider"),
        ("Token does not grant this permission", "auth.insufficient_permission"),
        ("Invalid bearer token", "auth.invalid_bearer"),
        ("something nobody anticipated", "auth.denied"),
    ],
)
def test_authentication_failures_map_to_distinct_codes(message, expected):
    """The unanticipated case falls to `auth.denied` rather than to whichever branch is last.

    A refusal reported under the wrong code sends an operator to debug the wrong thing, and
    `auth.denied` is the honest answer for a reason this table does not know.
    """
    assert planner_auth._failure_reason_code(RuntimeError(message)) == expected


# ---------------------------------------------------------------------------------------------
# `from_env` — misconfiguration reported as a NAMED fault rather than a default.
# ---------------------------------------------------------------------------------------------


@pytest.fixture()
def clean_env(monkeypatch):
    for var in (
        "TPP_BASE_URL",
        "TPP_OIDC_PROVIDER",
        "TPP_AUTH_MODE",
        "TPP_ACCESS_TOKEN",
        "TPP_BOOTSTRAP_SIGNING_SECRET",
        "TPP_BOOTSTRAP_TOKEN_TTL_SECONDS",
        "TPP_OIDC_AUDIENCE",
        "TPP_OIDC_ROLE_MAP",
        "TPP_OIDC_ROLE_MAP_FILE",
    ):
        monkeypatch.delenv(var, raising=False)


def _base_env(monkeypatch):
    monkeypatch.setenv("TPP_BASE_URL", "https://tpp.example.com")
    monkeypatch.setenv("TPP_OIDC_PROVIDER", "azure_ad")


@pytest.mark.usefixtures("clean_env")
def test_an_unknown_auth_mode_is_reported_as_invalid(monkeypatch):
    """Silently falling back to a default mode would change how every request is authenticated.

    `from_env` does not raise — it collects every fault into `missing_config`/`invalid_config` and
    exposes `is_ready`, which is the better design: one call reports all of them rather than
    failing at the first and hiding the rest. The assertions follow that shape.
    """
    _base_env(monkeypatch)
    monkeypatch.setenv("TPP_AUTH_MODE", "not-a-mode")
    config = planner_auth.PlannerAuthConfig.from_env()
    assert "TPP_AUTH_MODE" in config.invalid_config
    assert not config.is_ready


@pytest.mark.parametrize("ttl", ["not-a-number", "0", "-30"])
@pytest.mark.usefixtures("clean_env")
def test_a_non_positive_or_unparseable_ttl_is_reported(monkeypatch, ttl):
    """A token lifetime of zero or nonsense must not become an unbounded or default one."""
    _base_env(monkeypatch)
    monkeypatch.setenv("TPP_AUTH_MODE", PlannerAuthMode.STATIC_TOKEN.value)
    monkeypatch.setenv("TPP_ACCESS_TOKEN", "a-token")
    monkeypatch.setenv("TPP_BOOTSTRAP_TOKEN_TTL_SECONDS", ttl)
    config = planner_auth.PlannerAuthConfig.from_env()
    assert "TPP_BOOTSTRAP_TOKEN_TTL_SECONDS" in config.invalid_config
    assert not config.is_ready


@pytest.mark.usefixtures("clean_env")
def test_an_unsupported_oidc_provider_is_reported(monkeypatch):
    monkeypatch.setenv("TPP_BASE_URL", "https://tpp.example.com")
    monkeypatch.setenv("TPP_OIDC_PROVIDER", "some-other-idp")
    monkeypatch.setenv("TPP_AUTH_MODE", PlannerAuthMode.STATIC_TOKEN.value)
    monkeypatch.setenv("TPP_ACCESS_TOKEN", "a-token")
    config = planner_auth.PlannerAuthConfig.from_env()
    assert "TPP_OIDC_PROVIDER" in config.invalid_config
    assert not config.is_ready


@pytest.mark.usefixtures("clean_env")
def test_a_fully_configured_environment_is_ready(monkeypatch):
    """The control for the three above: without it, a `from_env` that rejected EVERY environment
    would satisfy all of them."""
    _base_env(monkeypatch)
    monkeypatch.setenv("TPP_AUTH_MODE", PlannerAuthMode.STATIC_TOKEN.value)
    monkeypatch.setenv("TPP_ACCESS_TOKEN", "a-token")
    config = planner_auth.PlannerAuthConfig.from_env()
    assert config.is_ready, (config.missing_config, config.invalid_config)


@pytest.mark.usefixtures("clean_env")
def test_a_valid_ttl_is_accepted_and_kept(monkeypatch):
    """The complement of the TTL rejections: a good value must survive rather than be defaulted."""
    _base_env(monkeypatch)
    monkeypatch.setenv("TPP_AUTH_MODE", PlannerAuthMode.STATIC_TOKEN.value)
    monkeypatch.setenv("TPP_ACCESS_TOKEN", "a-token")
    monkeypatch.setenv("TPP_BOOTSTRAP_TOKEN_TTL_SECONDS", "900")
    config = planner_auth.PlannerAuthConfig.from_env()
    assert config.is_ready
    assert config.bootstrap_ttl_seconds == 900
