"""Short-lived, draft-scoped browser capabilities for trip-planner handoffs."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time

HANDOFF_COOKIE_NAME = "tpp_portal_handoff"
HANDOFF_COOKIE_MAX_AGE_SECONDS = 15 * 60
_SIGNING_SECRET_ENV = "TPP_HANDOFF_SIGNING_SECRET"


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def resolve_handoff_signing_secret() -> str:
    """Use a dedicated secret when available, otherwise the configured planner token."""

    secret = os.getenv(_SIGNING_SECRET_ENV, "").strip() or os.getenv(
        "TPP_ACCESS_TOKEN", ""
    ).strip()
    if len(secret) < 16:
        raise ValueError(
            "TPP handoff links require TPP_HANDOFF_SIGNING_SECRET or a TPP_ACCESS_TOKEN "
            "of at least 16 characters."
        )
    return secret


def issue_handoff_token(
    subject: str,
    *,
    secret: str,
    now: int | None = None,
    ttl_seconds: int = HANDOFF_COOKIE_MAX_AGE_SECONDS,
) -> str:
    """Return a signed, expiring capability for one pending or saved draft subject."""

    if not subject or "\n" in subject:
        raise ValueError("Handoff token subject must be a non-empty single line.")
    issued_at = int(time.time()) if now is None else now
    payload = f"{subject}\n{issued_at + ttl_seconds}".encode()
    signature = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
    return f"{_encode(payload)}.{_encode(signature)}"


def issue_pending_handoff_token(*, secret: str, now: int | None = None) -> str:
    """Return a capability that may complete one browser handoff form."""

    return issue_handoff_token(
        f"pending:{secrets.token_urlsafe(18)}", secret=secret, now=now
    )


def verify_handoff_token(
    token: str | None,
    *,
    secret: str,
    now: int | None = None,
) -> str | None:
    """Return the capability subject when signature and expiry are valid."""

    if not token or token.count(".") != 1:
        return None
    payload_text, signature_text = token.split(".", 1)
    try:
        payload = _decode(payload_text)
        signature = _decode(signature_text)
        subject, expires_text = payload.decode().split("\n", 1)
        expires_at = int(expires_text)
    except (UnicodeDecodeError, ValueError):
        return None
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
    current_time = int(time.time()) if now is None else now
    if not hmac.compare_digest(signature, expected) or current_time > expires_at:
        return None
    return subject
