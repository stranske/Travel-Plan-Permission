# Production Readiness Issue Drafts

These issue drafts follow the canonical agent issue structure documented in
[`docs/AGENT_ISSUE_FORMAT.md`](../AGENT_ISSUE_FORMAT.md).
They target the remaining gaps between the then-current well-tested service and
a more production-ready workflow portal.

## Status Update, 2026-05-09

Recent implementation rounds resolved most of these drafts:

- Portal workflow state now has durable SQLite/Postgres-backed persistence via
  `src/travel_plan_permission/persistence/`, with restart tests in
  `tests/python/test_http_service.py` and backend tests in
  `tests/python/test_portal_state_store.py`.
- Expense and accounting exports are now gated by approved manager-review or
  approved exception linkage, traveler/trip matching, and explicit
  reimbursement/accounting status options.
- Portal actions now use authenticated permission checks for request,
  review, artifact, exception, and admin surfaces, with role-aware templates and
  durable audit-event logging.

The remaining production-hardening boundary is narrower than these drafts now
imply: external identity provisioning, enterprise segregation-of-duties depth,
external accounting/ERP settlement writes, and record lifecycle/retention policy
for portal workflow records. Audit-event retention is already implemented
through `tpp-audit-prune`.

## Issue Draft 1: Persist Portal Workflow State Beyond A Single Service Run

## Why

The portal, manager review queue, exception flow, expense drafts, and audit
trail now exist, but they still live in process memory. That is good enough for
preview-style local use, not for a production-ready workflow where users expect
requests and decisions to survive restarts.

## Scope

Introduce durable storage for request drafts, manager reviews, exception
requests, expense drafts, and audit history, along with restart-safe portal
surfaces that can resume previously created workflow state.

## Non-Goals

- A full distributed workflow engine
- Mandatory adoption of a specific cloud database vendor in this issue
- Rebuilding the planner-facing API contract

## Tasks

- [x] Add a durable storage abstraction for portal requests, manager reviews, exception records, expense drafts, and audit events
- [x] Replace the in-memory `ReviewWorkflowStore` and portal draft stores with the new storage-backed implementation
- [x] Make portal home, request detail, manager review, expense review, and audit surfaces load previously saved state after a restart
- [ ] Add bounded retention and cleanup rules for portal workflow records suitable for local/dev use and future production configuration
- [x] Add tests that simulate restart-safe retrieval of requests, reviews, exceptions, expense drafts, and audit history
- [x] Update setup and operator docs to describe the default local persistence path and its production-facing expectations

## Acceptance Criteria

- [x] Requests, reviews, exceptions, expense drafts, and audit history survive a service restart
- [x] The portal UI can reopen saved workflow state without manual reconstruction
- [x] Restart and retrieval behavior is test-covered
- [x] Local docs explain how durable storage is configured and where it lives

## Implementation Notes

Relevant files:
- `src/travel_plan_permission/http_service.py`
- `src/travel_plan_permission/review_workflow.py`
- `src/travel_plan_permission/security.py`
- new persistence modules under `src/travel_plan_permission/`
- `tests/python/test_http_service.py`
- new persistence-focused tests under `tests/python/`

Reference docs:
- `docs/workflows.md`
- `docs/plan.md`
- `docs/planner-live-test-runbook.md`

## Issue Draft 2: Enforce Approval-Linked Expense And Reimbursement Workflow Integrity

## Why

The expense portal UI now exists, but it still accepts free-form request linkage
instead of proving that an expense report belongs to an actually approved
request. That is a correctness gap for production-style reimbursement handling.

## Scope

Bind expense and reimbursement work to approved request records, validate
traveler and trip linkage, and expose the resulting workflow status clearly in
the portal UI.

## Non-Goals

- Deep ERP or finance-system integration in this issue
- OCR perfection or advanced extraction models
- Rebuilding the base itinerary approval workflow

## Tasks

- [x] Replace free-form expense linkage with server-validated lookup against approved request records
- [x] Validate traveler, trip, and cost context against the approved request before allowing expense review or export
- [x] Add a bounded reimbursement state machine for draft, manager review, accounting review, reimbursed, and rejected states
- [x] Update expense and accounting views so invalid linkage and blocked transitions render deliberate user-visible errors
- [x] Add tests for nonexistent request IDs, mismatched traveler/trip data, invalid transitions, and export gating
- [x] Update docs to describe the delivered expense workflow and its remaining external accounting boundaries

## Acceptance Criteria

- [x] Expense flows cannot proceed against nonexistent or unapproved requests
- [x] Reimbursement state transitions are explicit, validated, and visible in the UI
- [x] Accounting export artifacts are tied to a validated approved request
- [x] Tests cover invalid linkages and main reimbursement transitions

## Implementation Notes

Relevant files:
- `src/travel_plan_permission/http_service.py`
- `src/travel_plan_permission/review_workflow.py`
- `src/travel_plan_permission/receipts.py`
- `src/travel_plan_permission/export.py`
- `src/travel_plan_permission/templates/portal_expense.html`
- `tests/python/test_http_service.py`
- `tests/python/test_receipts.py`
- `tests/python/test_export_service.py`

Reference docs:
- `docs/workflows.md`
- `docs/plan.md`
- `docs/planner-live-test-runbook.md`

## Issue Draft 3: Harden Portal Authentication And Role-Aware Review Surfaces

## Why

The repo has a strong security model and planner-facing auth contract, but the
portal still behaves like a local preview surface more than a production portal.
Production readiness requires explicit actor identity, role-aware access, and
auditable authorization behavior across traveler, manager, accounting, and
admin screens.

## Scope

Add a practical authenticated portal actor model, enforce role-aware access on
portal actions, and make authorization state visible in the UI and audit trail.

## Non-Goals

- Shipping every Stage 4 enterprise SSO requirement in one issue
- Replacing the existing planner token contract for API callers
- Building a full identity-provider marketplace

## Tasks

- [x] Define the portal actor/session model for local and production-style use
- [x] Enforce authentication and role checks on request submission, manager review, expense review, export, exception, and audit routes
- [x] Update templates to display current actor context and suppress or disable unauthorized actions
- [x] Record authorization failures and elevated actions in the audit trail
- [x] Add tests for traveler, manager, accounting, and admin access boundaries
- [x] Update local runbook and README guidance so portal auth expectations are explicit

## Acceptance Criteria

- [x] Portal actions require an authenticated actor with the correct role or permission
- [x] Unauthorized users receive bounded errors and no hidden side effects
- [x] Role-sensitive UI states are visible and test-covered
- [x] Docs explain how to run the portal locally with realistic actor context

## Implementation Notes

Relevant files:
- `src/travel_plan_permission/http_service.py`
- `src/travel_plan_permission/security.py`
- `src/travel_plan_permission/planner_auth.py`
- `src/travel_plan_permission/templates/`
- `tests/python/test_http_service.py`
- `tests/python/test_security_model.py`
- `tests/python/test_planner_auth.py`

Reference docs:
- `docs/workflows.md`
- `docs/plan.md`
- `docs/planner-live-test-runbook.md`
