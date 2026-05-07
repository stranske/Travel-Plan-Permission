"""Deterministic cross-repo smoke harness for trip-planner plus TPP."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

from .persistence import resolve_portal_state_store
from .planner_client import (
    PlannerTransportError,
    Transport,
    TravelPlanPermissionClient,
    urllib_transport,
)
from .policy_api import (
    PlannerProposalOperationResponse,
)

_FIXTURE_ROOT: Traversable = resources.files("travel_plan_permission").joinpath(
    "fixtures", "planner_integration"
)
_TRIP_PLANNER_ROOT_ENV = "TRIP_PLANNER_REPO"
_TRIP_PLANNER_PROPOSAL_FIXTURE = Path(
    "tests/fixtures/integrations/tpp/proposal_submit_deferred.json"
)
_TRIP_PLANNER_REQUIRED_FILES = (
    Path("docs/contracts/tpp-proposal-execution.md"),
    Path("docs/contracts/tpp-execution-contracts.md"),
    _TRIP_PLANNER_PROPOSAL_FIXTURE,
)
_DEFAULT_PROPOSAL_VERSION = "proposal-v1"
_PORTAL_STATE_ENV_VAR = "TPP_PORTAL_STATE_PATH"
_PORTAL_STATE_DEFAULT_PATH = Path("var") / "portal-runtime-state.sqlite3"
_SUBMIT_OPERATION = "submit_proposal"
_POLL_OPERATION = "poll_execution_status"


class CrossRepoSmokeError(RuntimeError):
    """Raised when the cross-repo smoke contract cannot be proven."""


@dataclass(frozen=True)
class CrossRepoSmokeResult:
    """Summary of the deterministic cross-repo smoke result."""

    trip_planner_root: Path
    state_path: Path
    trip_id: str
    proposal_id: str
    execution_id: str
    outcome: str


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tpp-cross-repo-smoke",
        description=(
            "Validate trip-planner contract fixtures against the local TPP policy "
            "API/store and prove proposal status/evaluation survive a store reload."
        ),
    )
    parser.add_argument(
        "--trip-planner-root",
        default=None,
        help=(
            "Path to a trip-planner checkout. Defaults to TRIP_PLANNER_REPO or "
            "../trip-planner from the current directory."
        ),
    )
    parser.add_argument(
        "--state-path",
        default=None,
        help=(
            "Path for the temporary TPP proposal state file. Defaults to an isolated "
            "file under a temporary directory."
        ),
    )
    return parser


def _load_json(path: Traversable | Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CrossRepoSmokeError(f"Required smoke fixture is missing: {path}") from exc
    if not isinstance(payload, dict):
        raise CrossRepoSmokeError(f"Smoke fixture must contain a JSON object: {path}")
    return payload


def _load_packaged_fixture(name: str) -> dict[str, object]:
    return _load_json(_FIXTURE_ROOT / name)


def _object_field(payload: dict[str, object], field: str, *, context: str) -> dict[str, object]:
    value = payload.get(field)
    if not isinstance(value, dict):
        raise CrossRepoSmokeError(f"{context} must include an object field: {field}.")
    if any(not isinstance(key, str) for key in value):
        raise CrossRepoSmokeError(f"{context}.{field} must use string keys.")
    return dict(value)


def _string_field(payload: dict[str, object], field: str, *, context: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise CrossRepoSmokeError(f"{context} must include a non-empty string field: {field}.")
    return value


def _resolve_trip_planner_root(configured_root: str | None) -> Path:
    root = configured_root or os.getenv(_TRIP_PLANNER_ROOT_ENV)
    if root is None:
        root = str(Path.cwd().parent / "trip-planner")
    resolved = Path(root).expanduser().resolve()
    missing = [str(path) for path in _TRIP_PLANNER_REQUIRED_FILES if not (resolved / path).exists()]
    if missing:
        raise CrossRepoSmokeError(
            "trip-planner checkout is missing required TPP contract files: " + ", ".join(missing)
        )
    return resolved


def _load_trip_planner_proposal_fixture(
    trip_planner_root: Path,
) -> tuple[dict[str, object], dict[str, object]]:
    fixture = _load_json(trip_planner_root / _TRIP_PLANNER_PROPOSAL_FIXTURE)
    request_payload = _object_field(
        fixture,
        "request",
        context="trip-planner proposal fixture",
    )
    response_payload = _object_field(
        fixture,
        "response",
        context="trip-planner proposal fixture",
    )
    if request_payload.get("operation") != _SUBMIT_OPERATION:
        raise CrossRepoSmokeError("trip-planner proposal fixture must submit a proposal.")
    if response_payload.get("operation") != _SUBMIT_OPERATION:
        raise CrossRepoSmokeError("trip-planner proposal fixture response must submit a proposal.")
    result_payload = _object_field(
        response_payload,
        "result_payload",
        context="trip-planner proposal fixture response",
    )
    _string_field(result_payload, "execution_id", context="trip-planner proposal result payload")
    return request_payload, response_payload


def _validate_trip_planner_contracts(
    trip_planner_root: Path,
) -> tuple[dict[str, object], dict[str, object]]:
    proposal_doc = (trip_planner_root / "docs/contracts/tpp-proposal-execution.md").read_text(
        encoding="utf-8"
    )
    execution_doc = (trip_planner_root / "docs/contracts/tpp-execution-contracts.md").read_text(
        encoding="utf-8"
    )
    request_payload, response_payload = _load_trip_planner_proposal_fixture(trip_planner_root)
    required_doc_phrases = (
        "Persist the returned `ProposalSubmissionRecord`",
        "status polling",
        "correlation identifiers",
    )
    docs = f"{proposal_doc}\n{execution_doc}"
    missing_phrases = [phrase for phrase in required_doc_phrases if phrase not in docs]
    if missing_phrases:
        raise CrossRepoSmokeError(
            "trip-planner TPP docs are missing required contract language: "
            + ", ".join(missing_phrases)
        )
    return request_payload, response_payload


def _proposal_request_from_trip_planner_fixture(
    request_payload: dict[str, object],
) -> dict[str, object]:
    trip_id = _string_field(request_payload, "trip_id", context="trip-planner proposal request")
    proposal_id = _string_field(
        request_payload,
        "proposal_id",
        context="trip-planner proposal request",
    )
    payload = _object_field(request_payload, "payload", context="trip-planner proposal request")
    proposal_version = request_payload.get("proposal_version")
    if not isinstance(proposal_version, str) or not proposal_version:
        # The current trip-planner fixture predates proposal_version; keep only that
        # compatibility default while deriving the rest of the envelope from trip-planner.
        proposal_version = _DEFAULT_PROPOSAL_VERSION
    proposal_request: dict[str, object] = {
        "trip_id": trip_id,
        "proposal_id": proposal_id,
        "proposal_version": proposal_version,
        "payload": payload,
    }
    for optional_field in (
        "request_id",
        "correlation_id",
        "transport_pattern",
        "organization_id",
        "submitted_at",
    ):
        value = request_payload.get(optional_field)
        if value is not None:
            proposal_request[optional_field] = value
    return proposal_request


def _assert_submit_echoes_planner_fixture(
    *,
    submit_contract: PlannerProposalOperationResponse,
    proposal_request: dict[str, object],
    response_payload: dict[str, object],
) -> None:
    if submit_contract.operation != response_payload.get("operation"):
        raise CrossRepoSmokeError("Proposal submission did not echo the planner operation.")
    if submit_contract.transport_pattern != proposal_request.get("transport_pattern", "deferred"):
        raise CrossRepoSmokeError("Proposal submission did not preserve transport_pattern.")
    for field in ("trip_id", "proposal_id", "proposal_version"):
        if submit_contract.result_payload.get(field) != proposal_request[field]:
            raise CrossRepoSmokeError(f"Proposal submission did not echo {field}.")


def _assert_status_contract(
    *,
    status_contract: PlannerProposalOperationResponse,
    execution_id: str,
) -> None:
    if status_contract.operation != _POLL_OPERATION:
        raise CrossRepoSmokeError("Reloaded status returned the wrong operation.")
    if status_contract.submission_status != "pending":
        raise CrossRepoSmokeError("Reloaded status did not preserve pending submission state.")
    if status_contract.result_payload.get("execution_id") != execution_id:
        raise CrossRepoSmokeError("Reloaded status returned the wrong execution_id.")
    execution_status = status_contract.execution_status
    if execution_status is None:
        raise CrossRepoSmokeError("Reloaded status did not include execution_status.")
    if execution_status.state != "deferred":
        raise CrossRepoSmokeError("Reloaded status did not preserve deferred execution state.")
    if execution_status.terminal is not False:
        raise CrossRepoSmokeError("Reloaded deferred execution status must remain non-terminal.")
    if execution_status.poll_after_seconds is None or execution_status.poll_after_seconds <= 0:
        raise CrossRepoSmokeError(
            "Reloaded deferred execution status must include positive poll_after_seconds."
        )


def _assert_state_store_reloads(
    *,
    state_path: Path,
    proposal_id: str,
    execution_id: str,
    trip_id: str,
) -> None:
    store = resolve_portal_state_store(state_path)
    if store is None:
        raise CrossRepoSmokeError(f"No store configured for state path: {state_path}")
    persisted = store.load_snapshot()
    store.close()
    if persisted is None:
        raise CrossRepoSmokeError(f"TPP proposal state was not written: {state_path}")
    proposals = persisted.get("proposals_by_execution_id")
    if not isinstance(proposals, dict) or execution_id not in proposals:
        raise CrossRepoSmokeError(
            "Persisted TPP proposal state does not contain the submitted execution_id."
        )
    stored = proposals[execution_id]
    if not isinstance(stored, dict):
        raise CrossRepoSmokeError("Persisted TPP proposal state has invalid entry shape.")
    request_payload = stored.get("request")
    trip_payload = stored.get("trip_plan")
    if not isinstance(request_payload, dict) or request_payload.get("proposal_id") != proposal_id:
        raise CrossRepoSmokeError("Persisted TPP proposal state lost the proposal_id.")
    if not isinstance(trip_payload, dict) or trip_payload.get("trip_id") != trip_id:
        raise CrossRepoSmokeError("Persisted TPP proposal state lost the trip/workspace id.")


def _resolve_base_url() -> str:
    base_url = os.getenv("TPP_BASE_URL", "").strip()
    if not base_url:
        raise CrossRepoSmokeError("TPP_BASE_URL is required for the live cross-repo smoke.")
    return base_url


def _resolve_planner_token() -> str:
    token = os.getenv("TPP_PLANNER_TOKEN") or os.getenv("TPP_ACCESS_TOKEN") or ""
    if not token.strip():
        raise CrossRepoSmokeError(
            "A planner bearer token is required. Set TPP_PLANNER_TOKEN or TPP_ACCESS_TOKEN."
        )
    return token.strip()


def _resolve_state_path(configured_path: Path | None) -> Path:
    env_path = os.getenv(_PORTAL_STATE_ENV_VAR)
    if env_path:
        resolved_env_path = Path(env_path).expanduser().resolve()
        if configured_path is not None and configured_path.resolve() != resolved_env_path:
            raise CrossRepoSmokeError(
                f"{_PORTAL_STATE_ENV_VAR} must match --state-path for live smoke persistence."
            )
        return resolved_env_path
    if configured_path is not None:
        return configured_path.resolve()
    return (Path.cwd() / _PORTAL_STATE_DEFAULT_PATH).resolve()


def run_cross_repo_smoke(
    *,
    trip_planner_root: Path,
    state_path: Path | None = None,
    transport: Transport | None = None,
    timeout: float = 10.0,
) -> CrossRepoSmokeResult:
    """Run the cross-repo smoke through the live planner-facing HTTP transport."""

    request_payload, response_payload = _validate_trip_planner_contracts(trip_planner_root)
    trip_plan = _load_packaged_fixture("proposal_submission.json")
    proposal_request = _proposal_request_from_trip_planner_fixture(request_payload)
    trip_id = _string_field(proposal_request, "trip_id", context="planner proposal request")
    trip_plan["trip_id"] = trip_id
    base_url = _resolve_base_url()
    token = _resolve_planner_token()
    resolved_state_path = _resolve_state_path(state_path)

    client = TravelPlanPermissionClient(
        base_url=base_url,
        token=token,
        timeout=timeout,
        transport=transport or urllib_transport,
    )
    try:
        submit_contract = client.submit_proposal(
            trip_plan=trip_plan,
            request_payload=proposal_request,
        )
        _assert_submit_echoes_planner_fixture(
            submit_contract=submit_contract,
            proposal_request=proposal_request,
            response_payload=response_payload,
        )
        result_payload = submit_contract.result_payload
        proposal_id = result_payload.get("proposal_id")
        execution_id = result_payload.get("execution_id")
        if not isinstance(proposal_id, str) or not proposal_id:
            raise CrossRepoSmokeError("Proposal submission did not return a proposal_id.")
        if not isinstance(execution_id, str) or not execution_id:
            raise CrossRepoSmokeError("Proposal submission did not return an execution_id.")

        _assert_state_store_reloads(
            state_path=resolved_state_path,
            proposal_id=proposal_id,
            execution_id=execution_id,
            trip_id=trip_id,
        )

        status_contract = client.poll_status(
            proposal_id=proposal_id,
            execution_id=execution_id,
        )
        _assert_status_contract(status_contract=status_contract, execution_id=execution_id)

        evaluation = client.fetch_evaluation_result(execution_id=execution_id)
        if evaluation.proposal_id != proposal_id or evaluation.execution_id != execution_id:
            raise CrossRepoSmokeError("Reloaded evaluation lost proposal/execution linkage.")
    except PlannerTransportError as exc:
        raise CrossRepoSmokeError(f"Live planner transport failed: {exc}") from exc

    return CrossRepoSmokeResult(
        trip_planner_root=trip_planner_root,
        state_path=resolved_state_path,
        trip_id=trip_id,
        proposal_id=proposal_id,
        execution_id=execution_id,
        outcome=evaluation.outcome,
    )


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        trip_planner_root = _resolve_trip_planner_root(args.trip_planner_root)
        state_path = Path(args.state_path).expanduser().resolve() if args.state_path else None
        result = run_cross_repo_smoke(
            trip_planner_root=trip_planner_root,
            state_path=state_path,
        )
        print(f"trip-planner contracts: ok at {result.trip_planner_root}")
        print(f"proposal submission: ok for {result.proposal_id}")
        print(f"proposal status reload: ok for {result.execution_id}")
        print(f"evaluation reload: ok with outcome {result.outcome}")
    except CrossRepoSmokeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
