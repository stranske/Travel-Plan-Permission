# Workloop State — Travel-Plan-Permission

## 2026-05-31T05:5xZ — opener (claude_code): issue #1129 → PR (ephemeral-state warning)

- **Lane:** opener (claude_code). Outcome: `new_issue`.
- **Issue:** #1129 "Make the default deployment retain portal state, or warn in-UI
  that submissions are ephemeral" (priority:normal, repo-review-approved). Oldest
  unlinked normal-tier candidate after #1128 (linked→#1132) etc.
- **Posture chosen:** ephemeral synthetic demo + in-UI warning (the smallest
  self-contained path; the Render deployment is explicitly SYNTHETIC-ONLY with
  `TPP_PORTAL_STATE_PATH=/tmp/...`). Avoids the "do not mandate paid Postgres"
  non-goal.
- **Branch:** `claude/issue-1129-ephemeral-banner` (matches registry claude prefix).
- **Changes:**
  - `http_service.py`: `_portal_state_is_ephemeral()` + `_path_is_under_tmp()`
    helpers; `state_ephemeral` wired into the `/portal` (`portal_home`) context.
    Durable when `TPP_PORTAL_DATABASE_URL` is set or the state path is outside a
    temp dir; ephemeral when state lives under `/tmp` (render default).
  - `templates/portal_home.html`: conditional `.banner` ("Ephemeral demo state —
    submissions are not retained") with `data-testid="ephemeral-state-banner"`.
  - `docs/deployment.md`: explicit state-retention posture section (ephemeral vs
    durable) + manual restart-verification acceptance checklist (promoted from
    README:151-156).
  - `tests/python/test_http_service.py`: `test_portal_home_warns_when_state_ephemeral`,
    `test_portal_home_omits_warning_when_state_durable`,
    `test_portal_state_is_ephemeral_classification`.
- **Validation:** new tests pass; deliberate-break (disable banner → ephemeral test
  fails) confirmed and restored; full `tests/python/test_http_service.py` = 108
  passed; `ruff check` + `ruff format --check` clean.
- **Next action:** wait_for_keepalive. Opener is done with this lane once `pr_opened`
  fires.
