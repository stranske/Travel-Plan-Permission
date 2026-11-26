# Post-merge CI and sync-core evidence for PR #1767 after #1770 (#1772)

Evidence only; no code change. PR #1770 (merged as 0f55ab9 at 2026-11-26T05:46:44Z) delivered the fix. This records that it holds on the regenerated sync PR #1767.

## Task 1: #1767 regenerated beyond cda2862

- Workflows `maint-68-sync-consumer-repos.yml` run 45768704693 (job "Sync stranske/Travel-Plan-Permission": success) refreshed #1767.
- `gh pr view 1767 --repo stranske/Travel-Plan-Permission --json headRefOid,statusCheckRollup` returned `headRefOid` `410d6c53e194b2f6000b5685b22fc5880b7fe24a` (updated 2026-11-26T06:32:34Z).

## Task 2 / AC1: Python CI / python 3.13 SUCCESS on #1767

- Gate run 45768906763 on head 410d6c5. Attempt 1 failed only `generated delivery seal` / `classify changed paths` with `delivery_not_sealed:staging`, the designed hold until Maint 71 seals the exact head. Python CI did not run in that attempt.
- After Maint 71 sealed the head, attempt 2 concluded **success** (2026-11-26T06:38:21Z). Every non-skipped job succeeded, including `Python CI / python 3.13` (job 139737258244), `Python CI / python 3.14` and `Cross-Repo Smoke (trip-planner)`.
- `gh run view 45768906763 --repo stranske/Travel-Plan-Permission --job 139737258244 --log`: `1685 passed, 4 skipped, 3 xfailed`; there are 0 lines matching `CrossRepoSmokeError|HTTP 409`.
- Before the fix: Gate run 45758987542 on cda2862 failed `Python CI / python 3.13`, `Python CI / python 3.14` and `Cross-Repo Smoke (trip-planner)`.

## AC2: local pytest under Python 3.13

`uv run --python 3.13 --with pytest python -m pytest tests/python/test_cross_repo_smoke.py -q` on main 0f55ab9: `37 passed, 1 warning in 9.61s`, with no CrossRepoSmokeError and no HTTP 409.

## Task 3 / AC3: sync-core classification

From `~/.codex/orchestrator/sync-core/rounds.jsonl`, for target `stranske/Travel-Plan-Permission#1767`:

| Round | Disposition | Reasons |
|---|---|---|
| 20261126T063103Z (before the green Gate) | `repair-refresh-pending` | `Python CI / python 3.13: failed, unclassified`, `Python CI / python 3.14: failed, unclassified`, `Cross-Repo Smoke (trip-planner): failed, unclassified`, ... |
| 20261126T064535Z (first round after the green Gate) | `ready-for-maint71` | `maint71: campaign_prepared; next=merge-current-delivery` only |
| 20261126T065933Z | `ready-for-maint71` | same |

The next sync-core round classifies #1767 without the `tests/python/test_cross_repo_smoke.py` finding. Sync-core does not post its classification as a PR comment: `gh pr view 1767 --json comments` holds only the CodeRabbit skip notice and the Gate-followups fingerprint. The round ledger is the source.

## Notes

- After this evidence was collected, maint-68 restaged #1767 again to head 62f3438. Gate run 45772782907 on that head holds on the same `delivery_not_sealed:staging` seal precondition, the normal restage cycle. It is not a test regression.
- The closer-core revive comment said the wake condition held because of "1 success run" of `pr-00-gate.yml`. That run was 45768248453 on branch `codex/issue-1768`, not on #1767. The park-triage probe counts Gate successes repo-wide, not on the target PR, so it can wake an issue before its stated condition (Gate success on #1767) holds. Here #1767 went green within minutes anyway.
