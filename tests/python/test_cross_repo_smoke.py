from __future__ import annotations

import json
from pathlib import Path

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
    assert (
        "trip-planner checkout is missing required TPP contract files" in captured.err
    )
