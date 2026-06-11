## 2026-06-11T10:07:47Z - opener (codex): issue #1186 -> PR #1187

- Repo: `stranske/Travel-Plan-Permission`
- Issue: `#1186` - Cross-repo smoke: persist and assert TripState follow-up state after live HTTP evaluation
- PR: `#1187` - Persist TripState smoke records by execution
- Branch: `codex/issue-1186-tripstate-http-smoke`
- Worktree: `/Users/teacher/.codex/automations/pd-workloop-resume/worktrees/travel-1186-tripstate-smoke`
- Change: registered `trip_states_by_execution_id` as a per-record SQL snapshot namespace so TripState smoke persistence survives SQLite/Postgres reloads with the same keyed-record behavior as proposal state.
- Tests:
  - `PYTHONPATH=src python -m pytest tests/python/test_cross_repo_smoke.py::test_cross_repo_smoke_proves_submission_status_evaluation_and_reload tests/python/test_cross_repo_smoke.py::test_cross_repo_smoke_persists_trip_state_after_evaluation tests/python/test_portal_state_store.py::TestSQLitePortalStateStore::test_trip_state_records_round_trip_by_execution_id tests/python/test_portal_state_store.py::TestSQLitePortalStateStore::test_trip_state_namespace_reconciles_absent_records -v` passed.
  - `git diff --check` passed.
- Routing: PR is non-draft with `agent:codex`, `agents:keepalive`, `autofix`, `repo-review-approved`, and `priority:high`.
- Cap-health immediately after PR creation reported `needs-dispatch-evidence` because the first Gate/Gate Followups runs were cancelled; this state update is being pushed as a newer branch head before rerunning repair/cap-health.
- Next action: wait for keepalive/Gate evidence on the latest head.
