from __future__ import annotations

import json
from pathlib import Path

import pytest

from travel_plan_permission.cross_repo_smoke import main, run_cross_repo_smoke
from travel_plan_permission.persistence import resolve_portal_state_store


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


def test_cross_repo_smoke_proves_submission_status_evaluation_and_reload(
    tmp_path: Path,
) -> None:
    trip_planner_root = tmp_path / "trip-planner"
    _write_trip_planner_contracts(trip_planner_root)
    state_path = tmp_path / "tpp-state.sqlite3"

    result = run_cross_repo_smoke(
        trip_planner_root=trip_planner_root,
        state_path=state_path,
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
    monkeypatch.setenv("TRIP_PLANNER_REPO", str(trip_planner_root))

    exit_code = main([])

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
    # Simulate CWD being inside the TPP checkout (tmp_path / "travel-plan-permission")
    tpp_dir = tmp_path / "travel-plan-permission"
    tpp_dir.mkdir()
    monkeypatch.delenv("TRIP_PLANNER_REPO", raising=False)
    monkeypatch.chdir(tpp_dir)

    exit_code = main([])

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
