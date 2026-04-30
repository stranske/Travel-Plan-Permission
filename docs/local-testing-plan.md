# Local Testing Plan

This document is the repo-local testing plan for `Travel-Plan-Permission`. It
extends the planner live-test runbook with a broader workflow checklist that
covers automated tests, planner-facing APIs, and the browser portal.

## Goals

- verify the service and portal still pass their baseline automated checks,
- confirm the planner-facing HTTP contract works against a live local process,
- exercise the browser workflow portal and reviewer surfaces intentionally,
- make current maturity gaps visible during local testing instead of discovering them late.

## Local Setup

Preferred setup from the repo root:

```bash
uv sync --extra dev
```

If you prefer plain pip:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Stage 1: Full Automated Suite

Run this first:

```bash
python -m pytest -q
```

Use `uv run pytest -q` only if your environment is not shadowed by another
editable checkout. The cleanest local signal is the repo-local interpreter.

If the full suite fails, do not continue to manual portal testing until the
baseline is green.

## Stage 2: Planner API Live Smoke

Follow the runtime contract from
[`docs/planner-live-test-runbook.md`](planner-live-test-runbook.md).
The shortest useful loop is:

```bash
export TPP_BASE_URL="http://127.0.0.1:8000"
export TPP_OIDC_PROVIDER="google"
export TPP_AUTH_MODE="bootstrap-token"
export TPP_BOOTSTRAP_SIGNING_SECRET="replace-with-a-local-preview-secret"
tpp-planner-service --host 127.0.0.1 --port 8000
```

In a second shell:

```bash
curl -s http://127.0.0.1:8000/healthz
curl -s http://127.0.0.1:8000/readyz
tpp-planner-token --subject trip-planner-local
tpp-planner-smoke
```

This stage verifies:

- readiness and auth config,
- the planner snapshot route,
- proposal submission and status lookup,
- evaluation-result retrieval over a live local process.

## Stage 3: Portal Request Flow Review

With the service still running, open `http://127.0.0.1:8000/portal` and test:

1. Request creation from `/portal/requests/new`.
2. Validation feedback for missing required fields.
3. Review rendering from `/portal/requests/{draft_id}`.
4. Itinerary and summary artifact download links.
5. Request submission through the portal-backed workflow path.

Capture the `draft_id` and any generated review or artifact URLs when reporting
bugs.

## Stage 4: Reviewer And Portal UI Checks

For changes that touch workflow UI, explicitly verify:

1. Manager review queue and detail screens.
2. Exception request and exception decision surfaces.
3. Expense portal entry and review screens.
4. Error states for invalid input, blocked transitions, and missing artifacts.

Do not limit this stage to happy-path clicks. Confirm that user-visible error
copy is deliberate and that blocked actions do not silently succeed.

## Stage 5: Persistence And Restart Checks

Portal state now persists through a transactional SQL store. The default
backend is SQLite at `var/portal-runtime-state.sqlite3` (WAL journal mode);
override with `TPP_PORTAL_STATE_PATH` for a different local path or set
`TPP_PORTAL_DATABASE_URL` to point the service at Postgres for shared
staging. To force the deprecated single-file JSON backend, pass a
`.json`-suffixed path or set `TPP_PORTAL_BACKEND=json`. Run at least one
restart-oriented local check whenever you touch portal workflow state:

1. Create a request draft and, if relevant, submit it for review.
2. Create any relevant exception or expense draft.
3. Stop the service.
4. Restart the service.
5. Re-open the same portal URLs and verify state is preserved.

For multi-instance staging, also exercise the same flow against a Postgres
URL: two service instances pointing at the same database should each see the
other instance's drafts after a refresh, since per-record upserts at the SQL
layer prevent lost writes between processes.

Treat any restart-sensitive data loss as a regression to file rather than as
an ambiguous flake.

## Stage 6: Expense And Accounting Integrity Checks

For changes touching expense or reimbursement logic, verify:

1. expense review with a valid approved request,
2. rejection of nonexistent or mismatched request linkage,
3. receipt-present and receipt-missing states,
4. policy warning states,
5. accounting artifact generation,
6. blocked export or reimbursement actions when workflow state is invalid.

This stage matters because workflow integrity is more important than raw page
rendering for the expense surfaces.

## Stage 7: Cross-Repo Integration With trip-planner

If the change affects the planner-facing API contract:

1. Start this service locally.
2. In `trip-planner`, export matching TPP env vars.
3. Run `make runtime-dev` in `trip-planner`.
4. Submit a planner proposal from the workspace.
5. Confirm the execution lifecycle and evaluation result are reflected correctly
   on the `trip-planner` side.

Use this stage for contract and behavior changes, not every small local edit.

### CI gate: `cross-repo-smoke`

The same contract is gated automatically in CI by the `cross-repo-smoke` job in
`.github/workflows/ci.yml`. The job:

1. Checks out this repo (PR head).
2. Checks out `stranske/trip-planner` at `TRIP_PLANNER_PINNED_REF` into a
   sibling-like path (`${{ github.workspace }}/trip-planner`).
3. Installs this repo's `[dev,orchestration]` extras.
4. Generates a fresh `TPP_BOOTSTRAP_SIGNING_SECRET` and mints a bootstrap token
   via `tpp-planner-token`.
5. Starts `tpp-planner-service` on `127.0.0.1:8000` in the background and waits
   for `/readyz` to return `200`.
6. Runs `tpp-cross-repo-smoke` against the live local service, with
   `TRIP_PLANNER_REPO` pointed at the trip-planner checkout so the harness's
   contract-doc and proposal-fixture lookups succeed.
7. Runs `tpp-planner-smoke` against the same service.
8. Tears down the background service in an `if: always()` step and uploads the
   service log on failure.

The job runs on every pull request and push to `main` and is intended to be
configured as a required check in branch protection so a TPP-side schema or
auth change cannot land green when it breaks the planner contract.

#### Bumping `TRIP_PLANNER_PINNED_REF`

The pin is stored once in `.github/trip-planner-pinned-ref`. The
`cross-repo-smoke` job in both `.github/workflows/ci.yml` and
`.github/workflows/pr-00-gate.yml` reads that file at runtime, so a bump is
a single-file edit. To advance it:

1. Pick a known-good `stranske/trip-planner` commit on `main` whose
   `docs/contracts/tpp-proposal-execution.md`,
   `docs/contracts/tpp-execution-contracts.md`, and
   `tests/fixtures/integrations/tpp/proposal_submit_deferred.json` are
   compatible with the changes in your TPP PR.
2. Replace the SHA in `.github/trip-planner-pinned-ref` with that commit.
3. In parallel, update the matching pin on the `trip-planner` side so the two
   advance together (the trip-planner counterpart is tracked by a paired issue).
4. Push and let `cross-repo-smoke` validate the pair on the PR.

If `cross_repo_smoke.py` ever needs to look up new files in the
trip-planner checkout, update `_TRIP_PLANNER_REQUIRED_FILES` in
`src/travel_plan_permission/cross_repo_smoke.py` and the pin in lockstep.

## Bug Report Minimums

When you find a problem, capture:

- branch or commit,
- exact command or portal URL,
- whether it failed in automated tests, planner smoke, or browser review,
- actor role or auth mode in use,
- request ID, review ID, draft ID, or trip ID involved,
- traceback, response payload, or rendered error copy.

## Exit Criteria

Treat the repo as locally ready for broader testing only when:

- `python -m pytest -q` passes,
- planner live smoke succeeds for contract-sensitive work,
- portal request and review flows have been checked in a browser,
- restart-sensitive workflow behavior has been explicitly reviewed when relevant,
- expense and accounting flows have been tested when those surfaces changed,
- cross-repo planner integration has been exercised for API-contract changes.
