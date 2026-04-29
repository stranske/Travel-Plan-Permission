# Planner Integration Contract

**Version:** 1.0
**Status:** Canonical first-pass contract for `trip-planner` consumers
**Last Updated:** April 11, 2026

## Purpose

This document defines the planner-facing integration seam between
`trip-planner` and `travel_plan_permission` (TPP). It covers:

- transport authentication expectations,
- versioning and freshness semantics,
- the end-to-end request and response handshake,
- repository-owned example fixtures that stay under automated validation.

The goal is to let `trip-planner` integrate without relying on undocumented
headers, hidden cache rules, or ad hoc payload interpretation.

For the operator-facing startup, auth bootstrap, and smoke-test procedure that
drives this contract over a live HTTP service, see the
[`Planner Live-Test Runbook`](../planner-live-test-runbook.md).

## Supported Flows

The current first-pass contract supports these planner-facing flows:

1. Policy snapshot fetch
2. Proposal submission
3. Proposal status readback
4. Policy evaluation result handling

Fixture files for each flow live under
`tests/fixtures/planner_integration/` and are validated in
`tests/python/test_planner_integration_contract.py`.

For live service validation, this repo also exposes the repo-native smoke
command `tpp-planner-smoke`. It uses those same fixtures to exercise the HTTP
handshake against a running TPP instance, checks `/readyz` before proceeding,
and verifies that unauthenticated snapshot access is rejected before running
the authorized planner flow.

Planner callers should use the concrete transport wrapper in
`travel_plan_permission.planner_client.TravelPlanPermissionClient` when they
need the operational proposal lifecycle:

- `submit_proposal(trip_plan=..., request_payload=...)` posts to
  `POST /api/planner/proposals` and returns a typed
  `PlannerProposalOperationResponse` with stable proposal and execution IDs.
- `poll_status(proposal_id=..., execution_id=...)` reads
  `GET /api/planner/proposals/{proposal_id}/executions/{execution_id}` without
  discarding the response body.
- `fetch_evaluation_result(execution_id=...)` reads
  `GET /api/planner/executions/{execution_id}/evaluation-result` and validates
  the typed evaluation contract.
- `wait_for_terminal_status(...)` performs bounded polling and raises
  `PlannerPollingTimeout` with the last non-terminal response when the execution
  does not finish within the caller's attempt budget.

The client uses `TPP_BASE_URL` and a bearer token from either
`TPP_ACCESS_TOKEN` (`TPP_AUTH_MODE=static-token`) or a bootstrap token minted
from `TPP_BOOTSTRAP_SIGNING_SECRET` (`TPP_AUTH_MODE=bootstrap-token`) when wired
through `tpp-planner-smoke`. `PlannerAuthConfig.from_env` also requires
`TPP_OIDC_PROVIDER`, including when `TPP_AUTH_MODE=static-token`.

## Transport Authentication

### Auth method

The current planner-facing snapshot seam is a bearer-token protected read
endpoint. The snapshot response itself publishes the auth contract:

- endpoint: `GET /api/planner/policy-snapshot`
- required permission: `view`
- supported SSO providers: `azure_ad`, `okta`, `google`

### Required config shape for planner callers

`trip-planner` should load these values from deployment configuration:

| Config | Required | Purpose |
| --- | --- | --- |
| `TPP_BASE_URL` | yes | Base URL for the TPP service |
| `TPP_OIDC_PROVIDER` | yes | Identity provider name used to mint the bearer token |
| `TPP_AUTH_MODE` | yes | Auth mode: `static-token` or `bootstrap-token` |
| `TPP_ACCESS_TOKEN` | when `TPP_AUTH_MODE=static-token` | Fixed bearer token presented to TPP |
| `TPP_BOOTSTRAP_SIGNING_SECRET` | when `TPP_AUTH_MODE=bootstrap-token` | Shared signing secret used to validate bounded bootstrap tokens |
| `TPP_BOOTSTRAP_TOKEN_TTL_SECONDS` | no | Lifetime for locally minted bootstrap tokens |
| `TPP_POLICY_SNAPSHOT_MAX_AGE_SECONDS` | no | Local cache TTL override for snapshot reuse |

### Expected request metadata

When calling the planner snapshot seam, `trip-planner` should send:

- `Authorization: Bearer <planner bearer token>`
- the `trip_id` in the request payload
- `known_policy_version` when a cached snapshot already exists
- `snapshot_generated_at` when the planner is re-checking a previously cached
  payload for freshness

For local or preview live testing, TPP can mint a bounded bootstrap token with
`tpp-planner-token`. The token is short-lived and still carries explicit
planner permissions (`view`, `create`) so endpoint authorization is exercised
instead of bypassed.

TPP returns the auth guidance for the seam inside `snapshot.auth`, so the
planner can compare its runtime config to the server-advertised contract.

## Versioning And Breaking Changes

### Snapshot version keys

Every policy snapshot response includes version metadata in
`snapshot.versioning`:

- `contract_version`
- `policy_version`
- `planner_known_policy_version`
- `compatible_with_planner_cache`
- `etag`

`trip-planner` should treat `versioning.etag` as the canonical cache validator
for the snapshot payload and should invalidate local guidance immediately when
`compatible_with_planner_cache` is `false`.

### Breaking change rule

When TPP introduces a breaking payload or semantics change for this seam, it
must do both of the following:

1. Update this contract document and the example fixtures in the same change.
2. Ensure the resulting payload differences change at least one of the published
   snapshot version keys or explicitly document the migration path in release
   notes.

## Integration Handshake

### 1. Fetch a policy snapshot

`trip-planner` requests policy guidance before presenting provider or
documentation requirements to the user.

- Call `get_policy_snapshot` semantics through the planner seam with the target
  `trip_id`.
- Cache the response by `versioning.etag` until it becomes stale or invalidated.
- Re-send `known_policy_version` and `snapshot_generated_at` when re-checking a
  cached payload.

### 2. Submit a proposal

`trip-planner` submits a `TripPlan` payload using the canonical trip proposal
shape. At submission time:

- `status` should normally be `submitted`.
- `selected_providers` should reflect the providers chosen by the planner.
- `expense_breakdown` and `expected_costs` should align with what the user saw
  in the planner UI.

### 3. Read proposal status

TPP returns the same canonical `TripPlan` shape for status readback, enriched
with:

- the latest `status`,
- immutable `approval_history`,
- any current `validation_results`,
- any `exception_requests` captured during review.

### 4. Consume policy evaluation results

TPP returns a `PlannerProposalEvaluationResult` whenever the planner needs the
current policy decision for a proposal.

- `outcome="compliant"` means the proposal is currently acceptable without more
  planner-side remediation.
- `outcome="non_compliant"` means one or more blocking issues or rejected
  states still need planner action.
- `outcome="exception_required"` means the proposal must stay linked to an
  in-flight exception workflow before it can succeed.
- `blocking_issues[].code` and `policy_result.issues[].context.rule_id` are the
  stable machine-readable join keys for UI copy, analytics, or follow-up
  handling.
- `score_explanation` is the ranking contract for business-mode preferences:
  hard policy errors set `hard_blocked=true` and force the final preference
  score to `0`, soft policy warnings subtract `10` points each, and preference
  tradeoffs subtract `5` points while the proposal remains rankable.

### 5. Persist planner-runtime follow-up state

When `trip-planner` submits or replays a proposal through the orchestration
smoke path, the policy result must be persisted in the shared
`travel_plan_permission.orchestration.graph.TripState` model. That state is the
canonical seam for broader orchestration work:

- `planner_turn` carries the planner input turn.
- `policy_result` carries the TPP policy evaluation.
- `checkpoint_metadata` records the persisted checkpoint identity and policy
  status.
- `planner_feedback` carries user feedback from the planner adjustment loop.
- `follow_up_action` records the planner-side next step.

Future integration work should use this state model for checkpoint save/load
and follow-up behavior; a policy call that only returns advisory output without
updating this state is not sufficient for the planner-runtime lifecycle.

## Example Fixtures

These fixtures are the repository-owned source of truth for planner integration
examples:

| Flow | Fixture |
| --- | --- |
| Policy snapshot request | `tests/fixtures/planner_integration/policy_snapshot_request.json` |
| Policy snapshot response | `tests/fixtures/planner_integration/policy_snapshot_response.json` |
| Proposal submission | `tests/fixtures/planner_integration/proposal_submission.json` |
| Proposal status | `tests/fixtures/planner_integration/proposal_status.json` |
| Evaluation result (compliant) | `tests/fixtures/planner_integration/evaluation_result_compliant.json` |
| Evaluation result (soft policy penalty) | `tests/fixtures/planner_integration/evaluation_result_soft_penalty.json` |
| Evaluation result (non-compliant) | `tests/fixtures/planner_integration/evaluation_result_non_compliant.json` |
| Evaluation result (exception-required) | `tests/fixtures/planner_integration/evaluation_result_exception_required.json` |

## Change Management

Any future change to the planner-facing seam should update all three of the
following together:

1. this contract document,
2. the affected JSON fixture(s),
3. the validating tests.
