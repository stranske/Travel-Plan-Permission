"""Live HTTP smoke test entrypoint for planner-facing TPP integration."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, request

from .planner_auth import PlannerAuthConfig, PlannerAuthMode, mint_bootstrap_token
from .policy_api import (
    PlannerPolicySnapshot,
    PlannerProposalEvaluationResult,
    PlannerProposalOperationResponse,
)
from .security import Permission

_FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "planner_integration"
_DEFAULT_TIMEOUT_SECONDS = 10.0
_FIXTURE_DIR_ENV = "TPP_PLANNER_FIXTURES_DIR"


class PlannerSmokeError(RuntimeError):
    """Raised when the live smoke command cannot complete successfully."""


@dataclass(frozen=True)
class JsonResponse:
    """Minimal JSON-aware HTTP response wrapper."""

    status_code: int
    body: Any
    text: str


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tpp-planner-smoke",
        description="Exercise the live planner-facing HTTP handshake against a running TPP service.",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Service base URL. Defaults to TPP_BASE_URL.",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Explicit bearer token. Defaults to the configured static token or a minted bootstrap token.",
    )
    parser.add_argument(
        "--subject",
        default="trip-planner-local",
        help="Subject to embed when minting a bootstrap token.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=_DEFAULT_TIMEOUT_SECONDS,
        help="Per-request timeout in seconds.",
    )
    parser.add_argument(
        "--fixtures-dir",
        default=None,
        help=(
            "Directory containing planner integration JSON fixtures. "
            f"Defaults to ${_FIXTURE_DIR_ENV} or the repo checkout fixtures."
        ),
    )
    return parser


def _resolve_fixture_root(args: argparse.Namespace) -> Path:
    configured_root = args.fixtures_dir or os.getenv(_FIXTURE_DIR_ENV)
    fixture_root = Path(configured_root).expanduser() if configured_root else _FIXTURE_ROOT
    if fixture_root.is_dir():
        return fixture_root
    raise PlannerSmokeError(
        "Planner smoke fixtures are unavailable. "
        f"Expected {_FIXTURE_ROOT}, or set {_FIXTURE_DIR_ENV} / --fixtures-dir "
        "when running outside a repo checkout."
    )


def _load_fixture(fixture_root: Path, name: str) -> dict[str, object]:
    fixture_path = fixture_root / name
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PlannerSmokeError(
            f"Required planner integration fixture is missing: {fixture_path}"
        ) from exc
    if not isinstance(payload, dict):
        raise PlannerSmokeError(f"Fixture {fixture_path} must contain a JSON object.")
    return payload


def _request_json(
    method: str,
    url: str,
    *,
    timeout: float,
    json_body: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
) -> JsonResponse:
    encoded_body = None
    request_headers = dict(headers or {})
    if json_body is not None:
        encoded_body = json.dumps(json_body).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    req = request.Request(url, data=encoded_body, headers=request_headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            status_code = response.status
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        status_code = exc.code
    except error.URLError as exc:
        raise PlannerSmokeError(f"{method} {url} failed: {exc.reason}") from exc

    body: Any = None
    if raw:
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = raw
    return JsonResponse(status_code=status_code, body=body, text=raw)


def _resolve_base_url(args: argparse.Namespace, config: PlannerAuthConfig) -> str:
    base_url = args.base_url or config.base_url
    if not base_url:
        raise PlannerSmokeError(
            "Planner smoke needs a service URL. Set TPP_BASE_URL or pass --base-url."
        )
    return base_url.rstrip("/")


def _resolve_token(
    args: argparse.Namespace,
    config: PlannerAuthConfig,
) -> str:
    if isinstance(args.token, str) and args.token:
        return args.token

    if config.auth_mode == PlannerAuthMode.STATIC_TOKEN:
        token = os.getenv("TPP_ACCESS_TOKEN")
        if token:
            return token
        raise PlannerSmokeError(
            "TPP_AUTH_MODE=static-token requires TPP_ACCESS_TOKEN for planner smoke."
        )

    if config.auth_mode == PlannerAuthMode.BOOTSTRAP_TOKEN:
        if config.oidc_provider is None:
            raise PlannerSmokeError("TPP_OIDC_PROVIDER must be set for bootstrap planner smoke.")
        secret = os.getenv("TPP_BOOTSTRAP_SIGNING_SECRET")
        if secret is None:
            raise PlannerSmokeError(
                "TPP_BOOTSTRAP_SIGNING_SECRET must be set to mint a bootstrap smoke token."
            )
        return mint_bootstrap_token(
            subject=args.subject,
            permissions=(Permission.VIEW, Permission.CREATE),
            provider=config.oidc_provider,
            secret=secret,
            expires_in_seconds=config.bootstrap_ttl_seconds or 900,
        )

    raise PlannerSmokeError(
        "Planner smoke needs TPP_AUTH_MODE to be configured as static-token or bootstrap-token."
    )


def _proposal_request(trip_plan: dict[str, object]) -> dict[str, object]:
    trip_id = trip_plan.get("trip_id")
    if not isinstance(trip_id, str) or not trip_id:
        raise PlannerSmokeError("Proposal submission fixture is missing a valid trip_id.")
    return {
        "trip_id": trip_id,
        "proposal_id": "proposal-123",
        "proposal_version": "proposal-v1",
        "payload": {"selected_options": ["flight-1", "hotel-3"]},
    }


def _expect_json_object(response: JsonResponse, *, step: str) -> dict[str, object]:
    if not isinstance(response.body, dict):
        raise PlannerSmokeError(
            f"{step} returned non-object JSON: status={response.status_code} body={response.text!r}"
        )
    return response.body


def _validate_readyz(base_url: str, *, timeout: float) -> None:
    response = _request_json("GET", f"{base_url}/readyz", timeout=timeout)
    payload = _expect_json_object(response, step="readiness check")
    if response.status_code != 200 or payload.get("status") != "ready":
        raise PlannerSmokeError(
            f"Planner service is not ready: status={response.status_code} payload={payload}"
        )
    print("readyz: service reports ready")


def _validate_unauthorized_snapshot(
    base_url: str,
    *,
    timeout: float,
    trip_plan: dict[str, object],
    snapshot_request: dict[str, object],
) -> None:
    response = _request_json(
        "GET",
        f"{base_url}/api/planner/policy-snapshot",
        timeout=timeout,
        json_body={"trip_plan": trip_plan, "request": snapshot_request},
    )
    if response.status_code != 401:
        raise PlannerSmokeError(
            f"Unauthorized snapshot probe expected 401, got {response.status_code}: {response.text}"
        )
    print("unauthorized probe: service rejects missing bearer token")


def _validate_smoke_flow(
    base_url: str,
    *,
    fixture_root: Path,
    timeout: float,
    token: str,
) -> None:
    trip_plan = _load_fixture(fixture_root, "proposal_submission.json")
    snapshot_request = _load_fixture(fixture_root, "policy_snapshot_request.json")
    headers = {"Authorization": f"Bearer {token}"}

    _validate_readyz(base_url, timeout=timeout)
    _validate_unauthorized_snapshot(
        base_url,
        timeout=timeout,
        trip_plan=trip_plan,
        snapshot_request=snapshot_request,
    )

    snapshot_response = _request_json(
        "GET",
        f"{base_url}/api/planner/policy-snapshot",
        timeout=timeout,
        headers=headers,
        json_body={"trip_plan": trip_plan, "request": snapshot_request},
    )
    snapshot_payload = _expect_json_object(snapshot_response, step="policy snapshot")
    if snapshot_response.status_code != 200:
        raise PlannerSmokeError(
            f"Policy snapshot failed: status={snapshot_response.status_code} payload={snapshot_payload}"
        )
    snapshot = PlannerPolicySnapshot.model_validate(snapshot_payload)
    print(f"policy snapshot: ok for trip {snapshot.trip_id}")

    proposal_request = _proposal_request(trip_plan)
    submit_response = _request_json(
        "POST",
        f"{base_url}/api/planner/proposals",
        timeout=timeout,
        headers=headers,
        json_body={"trip_plan": trip_plan, "request": proposal_request},
    )
    submit_payload = _expect_json_object(submit_response, step="proposal submission")
    if submit_response.status_code != 200:
        raise PlannerSmokeError(
            f"Proposal submission failed: status={submit_response.status_code} payload={submit_payload}"
        )
    submit = PlannerProposalOperationResponse.model_validate(submit_payload)
    execution_id = submit.result_payload.get("execution_id")
    if not isinstance(execution_id, str) or not execution_id:
        raise PlannerSmokeError(
            f"Proposal submission did not return a valid execution_id: {submit.result_payload}"
        )
    print(f"proposal submission: ok with execution {execution_id}")

    proposal_id = str(proposal_request["proposal_id"])
    status_response = _request_json(
        "GET",
        f"{base_url}/api/planner/proposals/{proposal_id}/executions/{execution_id}",
        timeout=timeout,
        headers=headers,
    )
    status_payload = _expect_json_object(status_response, step="proposal status")
    if status_response.status_code != 200:
        raise PlannerSmokeError(
            f"Proposal status failed: status={status_response.status_code} payload={status_payload}"
        )
    status_model = PlannerProposalOperationResponse.model_validate(status_payload)
    if status_model.result_payload.get("execution_id") != execution_id:
        raise PlannerSmokeError(
            "Proposal status response returned an execution_id that does not match submission."
        )
    print("proposal status: ok")

    evaluation_response = _request_json(
        "GET",
        f"{base_url}/api/planner/executions/{execution_id}/evaluation-result",
        timeout=timeout,
        headers=headers,
    )
    evaluation_payload = _expect_json_object(evaluation_response, step="evaluation result")
    if evaluation_response.status_code != 200:
        raise PlannerSmokeError(
            f"Evaluation result failed: status={evaluation_response.status_code} payload={evaluation_payload}"
        )
    evaluation = PlannerProposalEvaluationResult.model_validate(evaluation_payload)
    if evaluation.execution_id != execution_id:
        raise PlannerSmokeError(
            "Evaluation result response returned an execution_id that does not match submission."
        )
    expected_suffix = f"/proposals/{proposal_id}/executions/{execution_id}"
    if not evaluation.status_endpoint.endswith(expected_suffix):
        raise PlannerSmokeError(
            f"Evaluation result returned an unexpected status_endpoint: {evaluation.status_endpoint}"
        )
    print(f"evaluation result: ok with outcome {evaluation.outcome}")


def main(argv: list[str] | None = None) -> int:
    """Exercise the planner-facing HTTP seam over a live network socket."""

    parser = _build_parser()
    args = parser.parse_args(argv)
    config = PlannerAuthConfig.from_env()
    try:
        base_url = _resolve_base_url(args, config)
        fixture_root = _resolve_fixture_root(args)
        token = _resolve_token(args, config)
        _validate_smoke_flow(
            base_url,
            fixture_root=fixture_root,
            timeout=args.timeout,
            token=token,
        )
    except PlannerSmokeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print("Planner HTTP smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
