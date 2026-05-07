from __future__ import annotations

import ast
import inspect
import json
import os
import textwrap
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import pytest

import travel_plan_permission.cross_repo_smoke as cross_repo_smoke
from travel_plan_permission.cross_repo_smoke import (
    CrossRepoSmokeError,
    _assert_status_contract,
    _assert_submit_echoes_planner_fixture,
    _load_json,
    _object_field,
    _string_field,
    main,
    run_cross_repo_smoke,
)
from travel_plan_permission.http_service import PlannerProposalStore
from travel_plan_permission.persistence import resolve_portal_state_store
from travel_plan_permission.planner_client import PlannerJsonResponse
from travel_plan_permission.policy_api import (
    PlannerCorrelationId,
    PlannerProposalEvaluationRequest,
    PlannerProposalExecutionStatus,
    PlannerProposalOperationResponse,
    PlannerProposalStatusRequest,
    PlannerProposalSubmissionRequest,
    TripPlan,
    get_evaluation_result,
    poll_execution_status,
    submit_proposal,
)


def _write_trip_planner_contracts(root: Path) -> None:
    contracts = root / "docs" / "contracts"
    fixtures = root / "tests" / "fixtures" / "integrations" / "tpp"
    contracts.mkdir(parents=True)
    fixtures.mkdir(parents=True)
    (contracts / "tpp-proposal-execution.md").write_text(
        "\n".join(
            [
                "# TPP Proposal Submission And Result Storage",
                "Persist the returned `ProposalSubmissionRecord` with explicit linkage.",
                "The harness covers status polling after proposal submission.",
            ]
        ),
        encoding="utf-8",
    )
    (contracts / "tpp-execution-contracts.md").write_text(
        "\n".join(
            [
                "# TPP Execution Contracts",
                "Preserve correlation identifiers across every round-trip.",
            ]
        ),
        encoding="utf-8",
    )
    (fixtures / "proposal_submit_deferred.json").write_text(
        json.dumps(
            {
                "request": {
                    "operation": "submit_proposal",
                    "request_id": "req-submit-001",
                    "transport_pattern": "deferred",
                    "trip_id": "trip-planner-fixture-001",
                    "proposal_id": "planner-proposal-123",
                    "proposal_version": "planner-proposal-v2",
                    "organization_id": "org-fixture",
                    "payload": {"proposal_ref": "planner-proposal-123"},
                },
                "response": {
                    "operation": "submit_proposal",
                    "execution_status": {"state": "deferred", "terminal": False},
                    "result_payload": {"execution_id": "exec-001"},
                },
            }
        ),
        encoding="utf-8",
    )


def _configure_live_smoke_env(monkeypatch: pytest.MonkeyPatch, state_path: Path) -> None:
    monkeypatch.setenv("TPP_BASE_URL", "http://live-tpp.test")
    monkeypatch.setenv("TPP_PLANNER_TOKEN", "live-smoke-token")
    monkeypatch.setenv("TPP_PORTAL_STATE_PATH", str(state_path))


class _LivePlannerTransport:
    @staticmethod
    def _close_store(store: PlannerProposalStore) -> None:
        if store.store is not None:
            store.store.close()

    def __call__(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        json_body: dict[str, object] | None,
        timeout: float,
    ) -> PlannerJsonResponse:
        assert timeout > 0
        assert headers == {"Authorization": "Bearer live-smoke-token"}
        path = urlparse(url).path
        state_path = Path(os.environ["TPP_PORTAL_STATE_PATH"])
        store = PlannerProposalStore(state_path=state_path)
        try:
            return self._dispatch(method, path, json_body, store)
        finally:
            self._close_store(store)

    def _dispatch(
        self,
        method: str,
        path: str,
        json_body: dict[str, object] | None,
        store: PlannerProposalStore,
    ) -> PlannerJsonResponse:
        if method == "POST" and path == "/api/planner/proposals":
            assert isinstance(json_body, dict)
            trip_plan = TripPlan.model_validate(json_body["trip_plan"])
            proposal_request = PlannerProposalSubmissionRequest.model_validate(json_body["request"])
            response = submit_proposal(trip_plan, proposal_request)
            store.record_submission(trip_plan, proposal_request, response)
            return PlannerJsonResponse(200, response.model_dump(mode="json"), "")

        if method == "GET" and path.startswith("/api/planner/proposals/"):
            parts = path.split("/")
            proposal_id = parts[4]
            execution_id = parts[6]
            stored = store.lookup_submission(execution_id)
            assert stored is not None
            response = poll_execution_status(
                stored.trip_plan,
                PlannerProposalStatusRequest(
                    trip_id=stored.request.trip_id,
                    proposal_id=proposal_id,
                    proposal_version=stored.request.proposal_version,
                    execution_id=execution_id,
                ),
            )
            return PlannerJsonResponse(200, response.model_dump(mode="json"), "")

        if method == "GET" and path.startswith("/api/planner/executions/"):
            execution_id = path.split("/")[4]
            stored = store.lookup_submission(execution_id)
            assert stored is not None
            evaluation_response = get_evaluation_result(
                stored.trip_plan,
                PlannerProposalEvaluationRequest(
                    trip_id=stored.request.trip_id,
                    proposal_id=stored.request.proposal_id,
                    proposal_version=stored.request.proposal_version,
                    execution_id=execution_id,
                ),
            )
            return PlannerJsonResponse(200, evaluation_response.model_dump(mode="json"), "")

        return PlannerJsonResponse(404, {"detail": f"unhandled {method} {path}"}, "")


def test_cross_repo_smoke_proves_submission_status_evaluation_and_reload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trip_planner_root = tmp_path / "trip-planner"
    _write_trip_planner_contracts(trip_planner_root)
    state_path = tmp_path / "tpp-state.sqlite3"
    _configure_live_smoke_env(monkeypatch, state_path)

    result = run_cross_repo_smoke(
        trip_planner_root=trip_planner_root,
        state_path=state_path,
        transport=_LivePlannerTransport(),
    )

    assert result.trip_id == "trip-planner-fixture-001"
    assert result.proposal_id == "planner-proposal-123"
    assert result.execution_id
    assert result.outcome in {"compliant", "non_compliant", "exception_required"}
    store = resolve_portal_state_store(state_path)
    assert store is not None
    persisted = store.load_snapshot()
    store.close()
    assert persisted is not None
    assert result.execution_id in persisted["proposals_by_execution_id"]
    assert persisted["plans_by_trip_id"][result.trip_id]["trip_id"] == result.trip_id
    stored = persisted["proposals_by_execution_id"][result.execution_id]
    assert stored["request"]["proposal_version"] == "planner-proposal-v2"
    assert stored["request"]["payload"] == {"proposal_ref": "planner-proposal-123"}


def test_run_cross_repo_smoke_uses_live_client_instead_of_direct_policy_calls() -> None:
    source = textwrap.dedent(inspect.getsource(cross_repo_smoke.run_cross_repo_smoke))
    tree = ast.parse(source)
    direct_calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    method_calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert "TravelPlanPermissionClient" in direct_calls
    assert {
        "submit_proposal",
        "poll_status",
        "fetch_evaluation_result",
    }.issubset(method_calls)
    assert (
        not {
            "get_policy_snapshot",
            "submit_proposal",
            "poll_execution_status",
            "get_evaluation_result",
        }
        & direct_calls
    )


def test_cross_repo_smoke_cli_reports_missing_trip_planner_checkout(
    tmp_path: Path,
    capsys,
) -> None:
    missing_root = tmp_path / "missing-trip-planner"

    exit_code = main(["--trip-planner-root", str(missing_root)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "trip-planner checkout is missing required TPP contract files" in captured.err


def test_cross_repo_smoke_resolves_root_via_trip_planner_repo_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    """TRIP_PLANNER_REPO env var is used when no --trip-planner-root arg is given.

    This mirrors the sibling-checkout layout used by the cross-repo-smoke CI job,
    where the workflow sets TRIP_PLANNER_REPO=${{ github.workspace }}/trip-planner.
    """
    trip_planner_root = tmp_path / "trip-planner"
    _write_trip_planner_contracts(trip_planner_root)
    state_path = tmp_path / "env-state.sqlite3"
    _configure_live_smoke_env(monkeypatch, state_path)
    monkeypatch.setattr(cross_repo_smoke, "urllib_transport", _LivePlannerTransport())
    monkeypatch.setenv("TRIP_PLANNER_REPO", str(trip_planner_root))

    exit_code = main(["--state-path", str(state_path)])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "trip-planner contracts: ok" in captured.out


def test_cross_repo_smoke_resolves_root_via_sibling_checkout_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    """../trip-planner fallback is used when neither arg nor env var is set.

    This covers the local developer layout where the trip-planner repo is checked
    out as a sibling directory alongside Travel-Plan-Permission.
    """
    trip_planner_root = tmp_path / "trip-planner"
    _write_trip_planner_contracts(trip_planner_root)
    state_path = tmp_path / "fallback-state.sqlite3"
    _configure_live_smoke_env(monkeypatch, state_path)
    monkeypatch.setattr(cross_repo_smoke, "urllib_transport", _LivePlannerTransport())
    # Simulate CWD being inside the TPP checkout (tmp_path / "travel-plan-permission")
    tpp_dir = tmp_path / "travel-plan-permission"
    tpp_dir.mkdir()
    monkeypatch.delenv("TRIP_PLANNER_REPO", raising=False)
    monkeypatch.chdir(tpp_dir)

    exit_code = main(["--state-path", str(state_path)])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "trip-planner contracts: ok" in captured.out


def test_cross_repo_smoke_fails_when_fixture_operation_is_renamed(
    tmp_path: Path,
    capsys,
) -> None:
    """A fixture with a renamed operation (broken contract) causes exit code 1.

    This mirrors the scenario where submit_proposal is renamed on either side
    of the contract boundary — the harness catches the mismatch and fails the job.
    """
    trip_planner_root = tmp_path / "trip-planner"
    contracts = trip_planner_root / "docs" / "contracts"
    fixtures = trip_planner_root / "tests" / "fixtures" / "integrations" / "tpp"
    contracts.mkdir(parents=True)
    fixtures.mkdir(parents=True)
    (contracts / "tpp-proposal-execution.md").write_text(
        "# TPP Proposal Submission And Result Storage\n"
        "Persist the returned `ProposalSubmissionRecord` with explicit linkage.\n"
        "The harness covers status polling after proposal submission.\n",
        encoding="utf-8",
    )
    (contracts / "tpp-execution-contracts.md").write_text(
        "# TPP Execution Contracts\nPreserve correlation identifiers across every round-trip.\n",
        encoding="utf-8",
    )
    # Deliberately broken: operation renamed from "submit_proposal" to "submit_trip"
    (fixtures / "proposal_submit_deferred.json").write_text(
        json.dumps(
            {
                "request": {
                    "operation": "submit_trip",  # broken — was "submit_proposal"
                    "trip_id": "trip-001",
                    "proposal_id": "prop-001",
                    "payload": {},
                },
                "response": {
                    "operation": "submit_trip",
                    "execution_status": {"state": "deferred", "terminal": False},
                    "result_payload": {"execution_id": "exec-001"},
                },
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(["--trip-planner-root", str(trip_planner_root)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "must submit a proposal" in captured.err


# ---------------------------------------------------------------------------
# Unit tests for internal helpers — cover error branches not hit by integration
# ---------------------------------------------------------------------------


def _make_op_response(**kwargs) -> PlannerProposalOperationResponse:
    defaults: dict = {
        "operation": "submit_proposal",
        "submission_status": "pending",
        "request_id": "req-1",
        "correlation_id": PlannerCorrelationId(value="corr-1"),
        "transport_pattern": "deferred",
        "received_at": datetime.now(UTC),
    }
    defaults.update(kwargs)
    return PlannerProposalOperationResponse(**defaults)


def _make_exec_status(**kwargs) -> PlannerProposalExecutionStatus:
    defaults: dict = {
        "state": "deferred",
        "terminal": False,
        "summary": "deferred",
        "external_status": "202 Accepted",
        "poll_after_seconds": 30.0,
    }
    defaults.update(kwargs)
    return PlannerProposalExecutionStatus(**defaults)


# -- _load_json ---------------------------------------------------------------


def test_load_json_raises_for_missing_file(tmp_path: Path) -> None:
    with pytest.raises(CrossRepoSmokeError, match="Required smoke fixture is missing"):
        _load_json(tmp_path / "nonexistent.json")


def test_load_json_raises_for_non_dict_content(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(CrossRepoSmokeError, match="must contain a JSON object"):
        _load_json(path)


# -- _object_field ------------------------------------------------------------


def test_object_field_raises_when_value_is_not_dict() -> None:
    with pytest.raises(CrossRepoSmokeError, match="must include an object field"):
        _object_field({"key": "not-a-dict"}, "key", context="ctx")


def test_object_field_raises_for_non_string_keys() -> None:
    with pytest.raises(CrossRepoSmokeError, match=r"ctx\.key must use string keys"):
        _object_field({"key": {1: "integer-key"}}, "key", context="ctx")


# -- _string_field ------------------------------------------------------------


def test_string_field_raises_when_field_is_missing() -> None:
    with pytest.raises(CrossRepoSmokeError, match="must include a non-empty string field"):
        _string_field({}, "missing_key", context="ctx")


def test_string_field_raises_when_field_is_empty() -> None:
    with pytest.raises(CrossRepoSmokeError, match="must include a non-empty string field"):
        _string_field({"key": ""}, "key", context="ctx")


# -- _validate_trip_planner_contracts -----------------------------------------


def test_validate_contracts_raises_when_doc_phrases_missing(tmp_path: Path) -> None:
    contracts = tmp_path / "docs" / "contracts"
    fixtures = tmp_path / "tests" / "fixtures" / "integrations" / "tpp"
    contracts.mkdir(parents=True)
    fixtures.mkdir(parents=True)
    (contracts / "tpp-proposal-execution.md").write_text(
        "# TPP\nNo required phrases here.", encoding="utf-8"
    )
    (contracts / "tpp-execution-contracts.md").write_text(
        "# Contracts\nAlso missing.", encoding="utf-8"
    )
    (fixtures / "proposal_submit_deferred.json").write_text(
        json.dumps(
            {
                "request": {
                    "operation": "submit_proposal",
                    "trip_id": "t1",
                    "proposal_id": "p1",
                    "payload": {},
                },
                "response": {
                    "operation": "submit_proposal",
                    "result_payload": {"execution_id": "e1"},
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(CrossRepoSmokeError, match="missing required contract language"):
        from travel_plan_permission.cross_repo_smoke import _validate_trip_planner_contracts

        _validate_trip_planner_contracts(tmp_path)


def test_validate_contracts_raises_when_response_operation_wrong(tmp_path: Path) -> None:
    contracts = tmp_path / "docs" / "contracts"
    fixtures = tmp_path / "tests" / "fixtures" / "integrations" / "tpp"
    contracts.mkdir(parents=True)
    fixtures.mkdir(parents=True)
    (contracts / "tpp-proposal-execution.md").write_text(
        "Persist the returned `ProposalSubmissionRecord`\nstatus polling\n", encoding="utf-8"
    )
    (contracts / "tpp-execution-contracts.md").write_text(
        "correlation identifiers\n", encoding="utf-8"
    )
    (fixtures / "proposal_submit_deferred.json").write_text(
        json.dumps(
            {
                "request": {
                    "operation": "submit_proposal",
                    "trip_id": "t1",
                    "proposal_id": "p1",
                    "payload": {},
                },
                "response": {
                    "operation": "wrong_operation",  # broken response op
                    "result_payload": {"execution_id": "e1"},
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(CrossRepoSmokeError, match="fixture response must submit a proposal"):
        from travel_plan_permission.cross_repo_smoke import _validate_trip_planner_contracts

        _validate_trip_planner_contracts(tmp_path)


# -- _proposal_request_from_trip_planner_fixture (missing proposal_version) --


def test_cross_repo_smoke_uses_default_proposal_version_when_fixture_omits_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trip_planner_root = tmp_path / "trip-planner"
    contracts = trip_planner_root / "docs" / "contracts"
    fixtures = trip_planner_root / "tests" / "fixtures" / "integrations" / "tpp"
    contracts.mkdir(parents=True)
    fixtures.mkdir(parents=True)
    (contracts / "tpp-proposal-execution.md").write_text(
        "Persist the returned `ProposalSubmissionRecord`\nstatus polling\n", encoding="utf-8"
    )
    (contracts / "tpp-execution-contracts.md").write_text(
        "correlation identifiers\n", encoding="utf-8"
    )
    # Fixture intentionally omits proposal_version so the default is used
    (fixtures / "proposal_submit_deferred.json").write_text(
        json.dumps(
            {
                "request": {
                    "operation": "submit_proposal",
                    "trip_id": "trip-no-version",
                    "proposal_id": "prop-no-version",
                    "transport_pattern": "deferred",
                    "payload": {"ref": "p1"},
                },
                "response": {
                    "operation": "submit_proposal",
                    "result_payload": {"execution_id": "exec-no-version"},
                },
            }
        ),
        encoding="utf-8",
    )
    state_path = tmp_path / "state.sqlite3"
    _configure_live_smoke_env(monkeypatch, state_path)

    result = run_cross_repo_smoke(
        trip_planner_root=trip_planner_root,
        state_path=state_path,
        transport=_LivePlannerTransport(),
    )

    assert result.proposal_id == "prop-no-version"


# -- _assert_submit_echoes_planner_fixture ------------------------------------


def test_assert_submit_echoes_raises_on_operation_mismatch() -> None:
    contract = _make_op_response(
        operation="submit_proposal",
        result_payload={"trip_id": "t", "proposal_id": "p", "proposal_version": "v"},
    )
    with pytest.raises(CrossRepoSmokeError, match="did not echo the planner operation"):
        _assert_submit_echoes_planner_fixture(
            submit_contract=contract,
            proposal_request={
                "trip_id": "t",
                "proposal_id": "p",
                "proposal_version": "v",
                "transport_pattern": "deferred",
            },
            response_payload={"operation": "other_op"},
        )


def test_assert_submit_echoes_raises_on_transport_pattern_mismatch() -> None:
    contract = _make_op_response(
        transport_pattern="sync",
        result_payload={"trip_id": "t", "proposal_id": "p", "proposal_version": "v"},
    )
    with pytest.raises(CrossRepoSmokeError, match="did not preserve transport_pattern"):
        _assert_submit_echoes_planner_fixture(
            submit_contract=contract,
            proposal_request={
                "trip_id": "t",
                "proposal_id": "p",
                "proposal_version": "v",
                "transport_pattern": "deferred",
            },
            response_payload={"operation": "submit_proposal"},
        )


def test_assert_submit_echoes_raises_on_field_mismatch() -> None:
    contract = _make_op_response(
        result_payload={"trip_id": "wrong-trip", "proposal_id": "p", "proposal_version": "v"}
    )
    with pytest.raises(CrossRepoSmokeError, match="did not echo trip_id"):
        _assert_submit_echoes_planner_fixture(
            submit_contract=contract,
            proposal_request={
                "trip_id": "expected-trip",
                "proposal_id": "p",
                "proposal_version": "v",
                "transport_pattern": "deferred",
            },
            response_payload={"operation": "submit_proposal"},
        )


# -- _assert_status_contract --------------------------------------------------


def test_assert_status_contract_raises_on_wrong_operation() -> None:
    contract = _make_op_response(
        operation="submit_proposal",
        result_payload={"execution_id": "e1"},
        execution_status=_make_exec_status(),
    )
    with pytest.raises(CrossRepoSmokeError, match="wrong operation"):
        _assert_status_contract(status_contract=contract, execution_id="e1")


def test_assert_status_contract_raises_on_wrong_submission_status() -> None:
    contract = _make_op_response(
        operation="poll_execution_status",
        submission_status="succeeded",
        result_payload={"execution_id": "e1"},
        execution_status=_make_exec_status(),
    )
    with pytest.raises(CrossRepoSmokeError, match="preserve pending submission state"):
        _assert_status_contract(status_contract=contract, execution_id="e1")


def test_assert_status_contract_raises_on_execution_id_mismatch() -> None:
    contract = _make_op_response(
        operation="poll_execution_status",
        result_payload={"execution_id": "wrong-id"},
        execution_status=_make_exec_status(),
    )
    with pytest.raises(CrossRepoSmokeError, match="wrong execution_id"):
        _assert_status_contract(status_contract=contract, execution_id="expected-id")


def test_assert_status_contract_raises_when_execution_status_none() -> None:
    contract = _make_op_response(
        operation="poll_execution_status",
        result_payload={"execution_id": "e1"},
        execution_status=None,
    )
    with pytest.raises(CrossRepoSmokeError, match="did not include execution_status"):
        _assert_status_contract(status_contract=contract, execution_id="e1")


def test_assert_status_contract_raises_on_non_deferred_state() -> None:
    contract = _make_op_response(
        operation="poll_execution_status",
        result_payload={"execution_id": "e1"},
        execution_status=_make_exec_status(state="running"),
    )
    with pytest.raises(CrossRepoSmokeError, match="preserve deferred execution state"):
        _assert_status_contract(status_contract=contract, execution_id="e1")


def test_assert_status_contract_raises_when_terminal_true() -> None:
    contract = _make_op_response(
        operation="poll_execution_status",
        result_payload={"execution_id": "e1"},
        execution_status=_make_exec_status(terminal=True),
    )
    with pytest.raises(CrossRepoSmokeError, match="must remain non-terminal"):
        _assert_status_contract(status_contract=contract, execution_id="e1")


def test_assert_status_contract_raises_when_poll_after_seconds_none() -> None:
    contract = _make_op_response(
        operation="poll_execution_status",
        result_payload={"execution_id": "e1"},
        execution_status=_make_exec_status(poll_after_seconds=None),
    )
    with pytest.raises(CrossRepoSmokeError, match="positive poll_after_seconds"):
        _assert_status_contract(status_contract=contract, execution_id="e1")


# -- live runtime config ------------------------------------------------------


def test_cross_repo_smoke_requires_live_base_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trip_planner_root = tmp_path / "trip-planner"
    _write_trip_planner_contracts(trip_planner_root)
    monkeypatch.delenv("TPP_BASE_URL", raising=False)
    monkeypatch.setenv("TPP_PLANNER_TOKEN", "token")

    with pytest.raises(CrossRepoSmokeError, match="TPP_BASE_URL is required"):
        run_cross_repo_smoke(
            trip_planner_root=trip_planner_root,
            state_path=tmp_path / "state.sqlite3",
            transport=_LivePlannerTransport(),
        )


def test_cross_repo_smoke_fails_when_live_service_is_unreachable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trip_planner_root = tmp_path / "trip-planner"
    _write_trip_planner_contracts(trip_planner_root)
    monkeypatch.setenv("TPP_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("TPP_PLANNER_TOKEN", "dummy")
    monkeypatch.setenv("TPP_PORTAL_STATE_PATH", str(tmp_path / "state.sqlite3"))

    exit_code = main(
        [
            "--trip-planner-root",
            str(trip_planner_root),
            "--state-path",
            str(tmp_path / "state.sqlite3"),
        ]
    )

    assert exit_code == 1


# -- main with --state-path ---------------------------------------------------


def test_cross_repo_smoke_cli_accepts_explicit_state_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    trip_planner_root = tmp_path / "trip-planner"
    _write_trip_planner_contracts(trip_planner_root)
    state_path = tmp_path / "explicit-state.sqlite3"
    _configure_live_smoke_env(monkeypatch, state_path)
    monkeypatch.setattr(cross_repo_smoke, "urllib_transport", _LivePlannerTransport())

    exit_code = main(
        ["--trip-planner-root", str(trip_planner_root), "--state-path", str(state_path)]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "trip-planner contracts: ok" in captured.out
    assert state_path.exists()
