"""Explicit, validated receipt references for accounting exports."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class ReceiptDelivery:
    """Local references or a hosted adapter with independently verified expiry."""

    mode: str
    root: Path | None = None
    origin: str | None = None
    signer: Callable[[str, datetime], str] | None = None
    verifier: Callable[[str, str, datetime, datetime], bool] | None = None

    @staticmethod
    def _hosted_origin(url: str) -> tuple[str, str, int]:
        try:
            parsed = urlsplit(url)
            host = (parsed.hostname or "").lower().rstrip(".")
            if (
                parsed.scheme != "https"
                or not host
                or parsed.username is not None
                or parsed.password is not None
                or any(c.isspace() or ord(c) < 32 for c in url)
                or "\\" in url
                or host in {"example.com", "example.org", "example.net"}
                or host.endswith((".example.com", ".example.org", ".example.net", ".invalid"))
            ):
                raise ValueError
            port = parsed.port
            if port is not None and port < 1:
                raise ValueError
            return parsed.scheme, host, 443 if port is None else port
        except (ValueError, TypeError) as exc:
            raise ValueError(
                "Receipt delivery requires a real HTTPS origin and valid signer URL."
            ) from exc

    def resolve(self, reference: str, now: datetime) -> str:
        """Resolve a receipt now; never manufacture a timestamp-only URL."""
        if self.mode == "local-reference":
            return self._local_reference(reference)
        if self.mode != "hosted-signed":
            raise ValueError("Select receipt delivery mode local-reference or hosted-signed.")
        if self.origin is None or self.signer is None or self.verifier is None:
            raise ValueError("Hosted receipt delivery requires an origin, signer, and verifier.")
        origin = self._hosted_origin(self.origin)
        expires_at = now + timedelta(days=7)
        try:
            result = self.signer(reference, expires_at)
            if not isinstance(result, str) or self._hosted_origin(result) != origin:
                raise ValueError("Receipt signer URL must match the configured HTTPS origin.")
            if not self.verifier(result, reference, expires_at, now):
                raise ValueError(
                    "Receipt signer result failed signature, reference, or expiry validation."
                )
        except Exception as exc:
            raise ValueError(
                "Receipt delivery failed; check the hosted signer/verifier configuration."
            ) from exc
        return result

    def _local_reference(self, reference: str) -> str:
        if self.root is None:
            raise ValueError("Local receipt delivery requires a receipt root (TPP_RECEIPT_ROOT).")
        try:
            root = self.root.resolve(strict=True)
            relative = Path(reference)
            if relative.is_absolute() or urlsplit(reference).scheme:
                raise ValueError
            target = (root / relative).resolve(strict=True)
            if not target.is_relative_to(root) or not target.is_file():
                raise ValueError
            # Opening also verifies that the exporting process can read the reference.
            with target.open("rb"):
                pass
        except (OSError, ValueError, RuntimeError) as exc:
            raise ValueError(
                "Receipt cannot be resolved; place a readable file beneath TPP_RECEIPT_ROOT "
                "and use its relative path."
            ) from exc
        return target.as_uri()
