"""Deterministic cross-repo smoke harness for trip-planner plus TPP."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from .http_service import PlannerProposalStore, create_app
from .policy_api import PlannerProposalEvaluationResult, PlannerProposalOperationResponse

_FIXTURE_ROOT: Traversable = resources.files("travel_plan_permission").joinpath(
    "fixtures", "planner_integration"
)
_TRIP_PLANNER_ROOT_ENV = "TRIP_PLANNER_REPO"
_TRIP_PLANNER_PROPOSAL_FIXTURE = Path(
    "tests/fixtures/integrations/tpp/proposal_submit_deferred.json"
)
_AUTH_HEADER = {"Authorization": "Bearer cross-repo-smoke-token"}
_RUNTIME_ENV = {
    "TPP_BASE_URL": "http://testserver",
    "TPP_OIDC_PROVIDER": "google",
    "TPP_AUTH_MODE": "static-token",
    "TPP_ACCESS_TOKEN": "cross-repo-smoke-token",
}
_TRIP_PLANNER_REQUIRED_FILES = (
    Path("docs/contracts/tpp-proposal-execution.md"),
    Path("docs/contracts/tpp-execution-contracts.md"),
    _TRIP_PLANNER_PROPOSAL_FIXTURE,
)
_DEFAULT_PROPOSAL_VERSION = "proposal-v1"


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
            "Validate trip-planner contract fixtures against a local TPP test client "
            "and prove proposal status/evaluation survive a store reload."
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
    if request_payload.get("operation") != "submit_proposal":
        raise CrossRepoSmokeError("trip-planner proposal fixture must submit a proposal.")
    if response_payload.get("operation") != "submit_proposal":
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
    if status_contract.operation != "poll_execution_status":
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


@contextmanager
def _planner_runtime_env() -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in _RUNTIME_ENV}
    os.environ.update(_RUNTIME_ENV)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _expect_object(response: Any, *, step: str) -> dict[str, object]:
    if response.status_code != 200:
        raise CrossRepoSmokeError(
            f"{step} failed: status={response.status_code} payload={response.text}"
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise CrossRepoSmokeError(f"{step} returned non-object JSON: {payload!r}")
    return payload


def _assert_state_file_reloads(
    *,
    state_path: Path,
    proposal_id: str,
    execution_id: str,
    trip_id: str,
) -> None:
    if not state_path.exists():
        raise CrossRepoSmokeError(f"TPP proposal state file was not written: {state_path}")
    persisted = _load_json(state_path)
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


def run_cross_repo_smoke(
    *,
    trip_planner_root: Path,
    state_path: Path,
) -> CrossRepoSmokeResult:
    """Run the deterministic cross-repo smoke against a reloadable local TPP store."""

    request_payload, response_payload = _validate_trip_planner_contracts(trip_planner_root)
    trip_plan = _load_packaged_fixture("proposal_submission.json")
    snapshot_request = _load_packaged_fixture("policy_snapshot_request.json")
    proposal_request = _proposal_request_from_trip_planner_fixture(request_payload)
    trip_id = _string_field(proposal_request, "trip_id", context="planner proposal request")
    trip_plan["trip_id"] = trip_id
    snapshot_request["trip_id"] = trip_id

    with _planner_runtime_env():
        first_client = TestClient(create_app(PlannerProposalStore(state_path=state_path)))
        snapshot = first_client.request(
            "GET",
            "/api/planner/policy-snapshot",
            headers=_AUTH_HEADER,
            json={"trip_plan": trip_plan, "request": snapshot_request},
        )
        _expect_object(snapshot, step="policy snapshot")

        submit = first_client.post(
            "/api/planner/proposals",
            headers=_AUTH_HEADER,
            json={"trip_plan": trip_plan, "request": proposal_request},
        )
        submit_payload = _expect_object(submit, step="proposal submission")
        submit_contract = PlannerProposalOperationResponse.model_validate(submit_payload)
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

        _assert_state_file_reloads(
            state_path=state_path,
            proposal_id=proposal_id,
            execution_id=execution_id,
            trip_id=trip_id,
        )

        second_client = TestClient(create_app(PlannerProposalStore(state_path=state_path)))
        status_response = second_client.get(
            f"/api/planner/proposals/{proposal_id}/executions/{execution_id}",
            headers=_AUTH_HEADER,
        )
        status_payload = _expect_object(status_response, step="proposal status reload")
        status_contract = PlannerProposalOperationResponse.model_validate(status_payload)
        _assert_status_contract(status_contract=status_contract, execution_id=execution_id)

        evaluation_response = second_client.get(
            f"/api/planner/executions/{execution_id}/evaluation-result",
            headers=_AUTH_HEADER,
        )
        evaluation_payload = _expect_object(
            evaluation_response,
            step="evaluation result reload",
        )
        evaluation = PlannerProposalEvaluationResult.model_validate(evaluation_payload)
        if evaluation.proposal_id != proposal_id or evaluation.execution_id != execution_id:
            raise CrossRepoSmokeError("Reloaded evaluation lost proposal/execution linkage.")

    return CrossRepoSmokeResult(
        trip_planner_root=trip_planner_root,
        state_path=state_path,
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
        if args.state_path:
            state_path = Path(args.state_path).expanduser().resolve()
            result = run_cross_repo_smoke(
                trip_planner_root=trip_planner_root,
                state_path=state_path,
            )
        else:
            with tempfile.TemporaryDirectory(prefix="tpp-cross-repo-smoke-") as temp_dir:
                result = run_cross_repo_smoke(
                    trip_planner_root=trip_planner_root,
                    state_path=Path(temp_dir) / "planner-state.json",
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
