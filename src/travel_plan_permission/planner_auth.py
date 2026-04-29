"""Planner-facing auth configuration and bounded bootstrap token support."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

import httpx
import jwt

from .security import DEFAULT_ROLES, DEFAULT_SSO_PLANS, Permission, RoleName

_SUPPORTED_OIDC_PROVIDERS = ("azure_ad", "okta", "google")
_TOKEN_VERSION = "tppv1"
_DEFAULT_BOOTSTRAP_TTL_SECONDS = 900
_DEFAULT_JWKS_CACHE_TTL_SECONDS = 600
_MIN_SIGNING_SECRET_LENGTH = 16
_PLANNER_TOKEN_AUDIENCE = "planner-service"
_PLANNER_STATIC_TOKEN_SUBJECT = "planner-static-client"

_OIDC_PROVIDER_REGISTRY = {
    name: {"issuer": plan.issuer, "jwks_url": plan.jwks_uri}
    for name, plan in DEFAULT_SSO_PLANS.items()
}
_JWKS_CACHE: dict[str, tuple[float, dict[str, object]]] = {}
_JWKS_CACHE_LOCK = threading.Lock()


class PlannerAuthMode(StrEnum):
    """Configured planner-facing authentication mode."""

    STATIC_TOKEN = "static-token"
    BOOTSTRAP_TOKEN = "bootstrap-token"
    OIDC = "oidc"


class OIDCAuthenticationError(PermissionError):
    """Structured OIDC authentication failure."""

    def __init__(self, message: str, *, error_code: str = "invalid_token") -> None:
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True)
class PlannerAuthContext:
    """Authenticated caller context for planner-facing endpoints."""

    subject: str
    permissions: tuple[Permission, ...]
    provider: str
    expires_at: datetime | None
    auth_mode: PlannerAuthMode

    def can(self, permission: Permission) -> bool:
        """Return whether the caller has the required permission."""

        return permission in self.permissions


@dataclass(frozen=True)
class PlannerBootstrapTokenClaims:
    """Claims encoded inside a bounded bootstrap token."""

    sub: str
    permissions: tuple[Permission, ...]
    provider: str
    aud: str
    iat: int
    exp: int


@dataclass(frozen=True)
class PlannerAuthConfig:
    """Runtime config contract for planner-facing authentication."""

    base_url: str | None
    oidc_provider: str | None
    auth_mode: PlannerAuthMode | None
    access_token_configured: bool
    bootstrap_secret_configured: bool
    bootstrap_ttl_seconds: int | None
    oidc_audience: str | None
    oidc_role_map_configured: bool
    oidc_subject_claim: str
    missing_config: tuple[str, ...]
    invalid_config: tuple[str, ...]

    @classmethod
    def from_env(cls) -> PlannerAuthConfig:
        base_url = os.getenv("TPP_BASE_URL")
        oidc_provider = os.getenv("TPP_OIDC_PROVIDER")
        auth_mode_raw = os.getenv("TPP_AUTH_MODE")
        access_token = os.getenv("TPP_ACCESS_TOKEN")
        bootstrap_secret = os.getenv("TPP_BOOTSTRAP_SIGNING_SECRET")
        ttl_raw = os.getenv("TPP_BOOTSTRAP_TOKEN_TTL_SECONDS")
        oidc_audience = os.getenv("TPP_OIDC_AUDIENCE")
        oidc_role_map = os.getenv("TPP_OIDC_ROLE_MAP")
        oidc_subject_claim = os.getenv("TPP_OIDC_SUBJECT_CLAIM", "sub")

        missing: list[str] = []
        invalid: list[str] = []

        if not base_url:
            missing.append("TPP_BASE_URL")
        if not oidc_provider:
            missing.append("TPP_OIDC_PROVIDER")
        elif oidc_provider not in _SUPPORTED_OIDC_PROVIDERS:
            invalid.append("TPP_OIDC_PROVIDER")

        auth_mode: PlannerAuthMode | None = None
        if not auth_mode_raw:
            missing.append("TPP_AUTH_MODE")
        else:
            try:
                auth_mode = PlannerAuthMode(auth_mode_raw)
            except ValueError:
                invalid.append("TPP_AUTH_MODE")

        bootstrap_ttl_seconds: int | None = None
        if ttl_raw:
            try:
                bootstrap_ttl_seconds = int(ttl_raw)
            except ValueError:
                invalid.append("TPP_BOOTSTRAP_TOKEN_TTL_SECONDS")
            else:
                if bootstrap_ttl_seconds <= 0:
                    invalid.append("TPP_BOOTSTRAP_TOKEN_TTL_SECONDS")

        if auth_mode == PlannerAuthMode.STATIC_TOKEN and not access_token:
            missing.append("TPP_ACCESS_TOKEN")
        if auth_mode == PlannerAuthMode.BOOTSTRAP_TOKEN:
            if not bootstrap_secret:
                missing.append("TPP_BOOTSTRAP_SIGNING_SECRET")
            elif len(bootstrap_secret) < _MIN_SIGNING_SECRET_LENGTH:
                invalid.append("TPP_BOOTSTRAP_SIGNING_SECRET")
        if auth_mode == PlannerAuthMode.OIDC:
            if not oidc_audience:
                missing.append("TPP_OIDC_AUDIENCE")
            if oidc_role_map:
                try:
                    parsed_role_map = json.loads(oidc_role_map)
                except json.JSONDecodeError:
                    invalid.append("TPP_OIDC_ROLE_MAP")
                else:
                    if not isinstance(parsed_role_map, dict):
                        invalid.append("TPP_OIDC_ROLE_MAP")
                    else:
                        for role_name in parsed_role_map.values():
                            try:
                                RoleName(str(role_name))
                            except ValueError:
                                invalid.append("TPP_OIDC_ROLE_MAP")
                                break

        return cls(
            base_url=base_url,
            oidc_provider=oidc_provider,
            auth_mode=auth_mode,
            access_token_configured=bool(access_token),
            bootstrap_secret_configured=bool(bootstrap_secret),
            bootstrap_ttl_seconds=bootstrap_ttl_seconds or _DEFAULT_BOOTSTRAP_TTL_SECONDS,
            oidc_audience=oidc_audience,
            oidc_role_map_configured=bool(oidc_role_map),
            oidc_subject_claim=oidc_subject_claim,
            missing_config=tuple(missing),
            invalid_config=tuple(invalid),
        )

    @property
    def is_ready(self) -> bool:
        """Return whether planner-facing auth config is valid."""

        return not self.missing_config and not self.invalid_config


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(raw: str) -> bytes:
    padding = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(f"{raw}{padding}")


def _signed_token(payload: dict[str, object], secret: str) -> str:
    payload_bytes = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    encoded_payload = _b64url_encode(payload_bytes)
    signature = hmac.new(
        secret.encode("utf-8"),
        encoded_payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return f"{_TOKEN_VERSION}.{encoded_payload}.{_b64url_encode(signature)}"


def mint_bootstrap_token(
    *,
    subject: str,
    permissions: tuple[Permission, ...],
    provider: str,
    secret: str,
    expires_in_seconds: int,
    now: datetime | None = None,
) -> str:
    """Create a short-lived bootstrap bearer token for local or preview tests."""

    current_time = now or datetime.now(UTC)
    issued_at = int(current_time.timestamp())
    expires_at = int((current_time + timedelta(seconds=expires_in_seconds)).timestamp())
    payload = {
        "aud": _PLANNER_TOKEN_AUDIENCE,
        "exp": expires_at,
        "iat": issued_at,
        "permissions": [permission.value for permission in permissions],
        "provider": provider,
        "sub": subject,
    }
    return _signed_token(payload, secret)


def _parse_bootstrap_token(token: str, *, secret: str) -> PlannerBootstrapTokenClaims:
    try:
        version, encoded_payload, encoded_signature = token.split(".")
    except ValueError as exc:
        raise ValueError("Malformed bootstrap token.") from exc
    if version != _TOKEN_VERSION:
        raise ValueError("Unsupported bootstrap token version.")

    expected_signature = hmac.new(
        secret.encode("utf-8"),
        encoded_payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    actual_signature = _b64url_decode(encoded_signature)
    if not secrets.compare_digest(actual_signature, expected_signature):
        raise ValueError("Invalid bootstrap token signature.")

    try:
        payload = json.loads(_b64url_decode(encoded_payload))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Malformed bootstrap token payload.") from exc

    try:
        permissions = tuple(Permission(value) for value in payload["permissions"])
        return PlannerBootstrapTokenClaims(
            sub=str(payload["sub"]),
            permissions=permissions,
            provider=str(payload["provider"]),
            aud=str(payload["aud"]),
            iat=int(payload["iat"]),
            exp=int(payload["exp"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Malformed bootstrap token claims.") from exc


def _oidc_provider_settings(config: PlannerAuthConfig) -> dict[str, str]:
    if config.oidc_provider is None:
        raise ValueError("Planner auth config is not ready.")
    settings = _OIDC_PROVIDER_REGISTRY[config.oidc_provider]
    issuer = os.getenv("TPP_OIDC_ISSUER", settings["issuer"])
    jwks_url = os.getenv("TPP_OIDC_JWKS_URL", settings["jwks_url"])
    if "{" in issuer or "{" in jwks_url:
        raise ValueError("Planner OIDC provider requires TPP_OIDC_ISSUER and TPP_OIDC_JWKS_URL.")
    return {"issuer": issuer, "jwks_url": jwks_url}


def _fetch_jwks_document(jwks_url: str) -> dict[str, object]:
    response = httpx.get(jwks_url, timeout=5.0)
    response.raise_for_status()
    document = response.json()
    if not isinstance(document, dict) or not isinstance(document.get("keys"), list):
        raise OIDCAuthenticationError("OIDC JWKS document is malformed.")
    return document


def _get_cached_jwks(jwks_url: str, *, force_refresh: bool = False) -> dict[str, object]:
    now = time.monotonic()
    with _JWKS_CACHE_LOCK:
        cached = _JWKS_CACHE.get(jwks_url)
        if cached and not force_refresh and cached[0] > now:
            return cached[1]

    document = _fetch_jwks_document(jwks_url)
    with _JWKS_CACHE_LOCK:
        _JWKS_CACHE[jwks_url] = (now + _DEFAULT_JWKS_CACHE_TTL_SECONDS, document)
    return document


def _select_jwk(jwks: dict[str, object], kid: str | None) -> dict[str, object] | None:
    keys = jwks.get("keys")
    if not isinstance(keys, list):
        return None
    if kid is None and len(keys) == 1 and isinstance(keys[0], dict):
        return keys[0]
    for key in keys:
        if isinstance(key, dict) and key.get("kid") == kid:
            return key
    return None


def _role_permissions_for_claims(
    claims: dict[str, object], config: PlannerAuthConfig
) -> tuple[Permission, ...]:
    subject = str(claims.get(config.oidc_subject_claim) or claims["sub"])
    raw_role_map = os.getenv("TPP_OIDC_ROLE_MAP")
    role_name = RoleName.TRAVELER
    if raw_role_map:
        role_map = json.loads(raw_role_map)
        mapped = role_map.get(f"sub:{subject}", role_map.get(subject))
        if mapped is None:
            mapped = role_map.get(f"{config.oidc_subject_claim}:{subject}")
        if mapped is not None:
            role_name = RoleName(str(mapped))
    return tuple(sorted(DEFAULT_ROLES[role_name].permissions, key=lambda item: item.value))


def _verify_oidc_token(
    token: str,
    *,
    config: PlannerAuthConfig,
) -> PlannerAuthContext:
    settings = _oidc_provider_settings(config)
    if config.oidc_provider is None or config.oidc_audience is None:
        raise ValueError("Planner auth config is not ready.")

    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError as exc:
        raise OIDCAuthenticationError("OIDC bearer token is malformed.") from exc
    alg = header.get("alg")
    if not isinstance(alg, str) or alg == "none":
        raise OIDCAuthenticationError("OIDC bearer token algorithm is unsupported.")
    kid = header.get("kid")
    if kid is not None and not isinstance(kid, str):
        raise OIDCAuthenticationError("OIDC bearer token key id is invalid.")

    jwks = _get_cached_jwks(settings["jwks_url"])
    jwk = _select_jwk(jwks, kid)
    if jwk is None:
        jwks = _get_cached_jwks(settings["jwks_url"], force_refresh=True)
        jwk = _select_jwk(jwks, kid)
    if jwk is None:
        raise OIDCAuthenticationError("OIDC bearer token key id was not found.")

    try:
        signing_key = jwt.PyJWK.from_dict(jwk).key
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=[alg],
            audience=config.oidc_audience,
            issuer=settings["issuer"],
            options={"require": ["exp", "nbf", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise OIDCAuthenticationError("OIDC bearer token has expired.") from exc
    except jwt.InvalidAudienceError as exc:
        raise OIDCAuthenticationError("OIDC bearer token audience is invalid.") from exc
    except jwt.InvalidIssuerError as exc:
        raise OIDCAuthenticationError("OIDC bearer token issuer is invalid.") from exc
    except jwt.InvalidTokenError as exc:
        raise OIDCAuthenticationError("OIDC bearer token is invalid.") from exc

    subject = str(claims.get(config.oidc_subject_claim) or claims["sub"])
    permissions = _role_permissions_for_claims(claims, config)
    expires_at = datetime.fromtimestamp(int(claims["exp"]), tz=UTC)
    return PlannerAuthContext(
        subject=subject,
        permissions=permissions,
        provider=config.oidc_provider,
        expires_at=expires_at,
        auth_mode=PlannerAuthMode.OIDC,
    )


def authenticate_request(
    authorization: str | None,
    *,
    config: PlannerAuthConfig,
    required_permission: Permission,
    now: datetime | None = None,
) -> PlannerAuthContext:
    """Validate the request bearer token against the configured planner auth mode."""

    if not config.is_ready:
        raise ValueError("Planner auth config is not ready.")
    if authorization is None or not authorization.startswith("Bearer "):
        raise PermissionError("Missing bearer token.")

    token = authorization.removeprefix("Bearer ").strip()
    if config.auth_mode == PlannerAuthMode.STATIC_TOKEN:
        expected = os.getenv("TPP_ACCESS_TOKEN")
        if expected is None or not secrets.compare_digest(token, expected):
            raise PermissionError("Invalid bearer token.")
        permissions = (Permission.VIEW, Permission.CREATE)
        if required_permission not in permissions:
            raise PermissionError(
                f"Static planner token does not grant '{required_permission.value}'."
            )
        if config.oidc_provider is None:
            raise ValueError("Planner auth config is not ready.")
        return PlannerAuthContext(
            subject=_PLANNER_STATIC_TOKEN_SUBJECT,
            permissions=permissions,
            provider=config.oidc_provider,
            expires_at=None,
            auth_mode=PlannerAuthMode.STATIC_TOKEN,
        )

    if config.auth_mode == PlannerAuthMode.OIDC:
        context = _verify_oidc_token(token, config=config)
        if required_permission not in context.permissions:
            raise PermissionError(f"OIDC token role does not grant '{required_permission.value}'.")
        return context

    if config.auth_mode != PlannerAuthMode.BOOTSTRAP_TOKEN:
        raise ValueError("Unsupported planner auth mode.")

    secret = os.getenv("TPP_BOOTSTRAP_SIGNING_SECRET")
    if secret is None:
        raise ValueError("Planner auth config is not ready.")

    claims = _parse_bootstrap_token(token, secret=secret)
    if claims.aud != _PLANNER_TOKEN_AUDIENCE:
        raise PermissionError("Bootstrap token audience is invalid.")
    if config.oidc_provider is None or claims.provider != config.oidc_provider:
        raise PermissionError("Bootstrap token provider does not match service config.")

    current_time = now or datetime.now(UTC)
    if int(current_time.timestamp()) >= claims.exp:
        raise PermissionError("Bootstrap token has expired.")
    if required_permission not in claims.permissions:
        raise PermissionError(f"Bootstrap token does not grant '{required_permission.value}'.")
    return PlannerAuthContext(
        subject=claims.sub,
        permissions=claims.permissions,
        provider=claims.provider,
        expires_at=datetime.fromtimestamp(claims.exp, tz=UTC),
        auth_mode=PlannerAuthMode.BOOTSTRAP_TOKEN,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tpp-planner-token",
        description="Mint a bounded bootstrap token for planner-facing live tests.",
    )
    parser.add_argument(
        "--subject",
        default="trip-planner-local",
        help="Subject recorded in the minted bootstrap token.",
    )
    parser.add_argument(
        "--permission",
        action="append",
        dest="permissions",
        choices=[permission.value for permission in Permission],
        help="Permission to embed in the token. Defaults to view and create.",
    )
    parser.add_argument(
        "--expires-in",
        type=int,
        default=None,
        help="Token lifetime in seconds. Defaults to TPP_BOOTSTRAP_TOKEN_TTL_SECONDS or 900.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Print a bounded bootstrap token for local or preview planner tests."""

    parser = _build_parser()
    args = parser.parse_args(argv)
    config = PlannerAuthConfig.from_env()
    if config.auth_mode != PlannerAuthMode.BOOTSTRAP_TOKEN:
        parser.error("TPP_AUTH_MODE must be set to 'bootstrap-token' to mint planner tokens.")
    if not config.is_ready:
        parser.error(
            "Planner auth config is incomplete. Set TPP_BASE_URL, TPP_OIDC_PROVIDER, "
            "TPP_AUTH_MODE=bootstrap-token, and TPP_BOOTSTRAP_SIGNING_SECRET."
        )

    secret = os.getenv("TPP_BOOTSTRAP_SIGNING_SECRET")
    if secret is None or config.oidc_provider is None:
        parser.error("Planner auth config is incomplete.")

    permissions = tuple(
        Permission(permission)
        for permission in (args.permissions or [Permission.VIEW.value, Permission.CREATE.value])
    )
    token = mint_bootstrap_token(
        subject=args.subject,
        permissions=permissions,
        provider=config.oidc_provider,
        secret=secret,
        expires_in_seconds=args.expires_in or config.bootstrap_ttl_seconds or 900,
    )
    print(token)
    return 0
