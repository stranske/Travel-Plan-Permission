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

Because durable workflow state is still an active production-readiness gap, run
at least one restart-oriented local check whenever you touch portal workflow
state:

1. Create a request draft and, if relevant, submit it for review.
2. Create any relevant exception or expense draft.
3. Stop the service.
4. Restart the service.
5. Re-open the same portal URLs and verify whether state is preserved, missing,
   or intentionally reset.

Until durable persistence lands, treat any restart-sensitive data loss as a
known limitation to record explicitly in test notes, not as an ambiguous flake.

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
