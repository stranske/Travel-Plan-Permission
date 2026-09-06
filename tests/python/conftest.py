"""Test configuration for adding src to the import path."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC_PATH = ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))


@pytest.fixture(autouse=True)
def isolated_portal_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep default HTTP service state isolated across parallel test workers."""

    monkeypatch.setenv("TPP_PORTAL_STATE_PATH", str(tmp_path / "portal-runtime-state.sqlite3"))


@pytest.fixture
def receipt_hosted_delivery():
    """Offline hosted-adapter contract: bind receipt, exact expiry, and signature."""
    import hashlib
    import hmac
    from urllib.parse import parse_qs, urlencode, urlsplit

    from travel_plan_permission.receipt_delivery import ReceiptDelivery

    key = b"deterministic-receipt-test-key"
    origin = "https://receipts.finance.internal"

    def signature(reference, expires):
        return hmac.new(key, f"{reference}\n{expires}".encode(), hashlib.sha256).hexdigest()

    def signer(reference, expiry):
        expires = str(int(expiry.timestamp()))
        return (
            origin
            + "/receipt?"
            + urlencode(
                {
                    "receipt": reference,
                    "expires": expires,
                    "signature": signature(reference, expires),
                }
            )
        )

    def verifier(url, reference, expiry, now):
        try:
            params = parse_qs(urlsplit(url).query, keep_blank_values=True, strict_parsing=True)
            if set(params) != {"receipt", "expires", "signature"} or any(
                len(values) != 1 or not values[0] for values in params.values()
            ):
                return False
            expires = params["expires"][0]
            return (
                params["receipt"] == [reference]
                and int(expires) == int(expiry.timestamp())
                and now.timestamp() < int(expires)
                and hmac.compare_digest(params["signature"][0], signature(reference, expires))
            )
        except (ValueError, KeyError):
            return False

    return ReceiptDelivery("hosted-signed", origin=origin, signer=signer, verifier=verifier)
