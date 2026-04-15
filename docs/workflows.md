# Workflows (Lite)

## Itinerary (Stage 1–2)

Draft → Employee Submit → Manager Review → Board Secretary Review → Approved
→ Ready to Travel

Branches: Request Changes, Reject. No delegation/escalation in Stage 1–2.

### Workflow portal contract

The Stage 2 browser portal now uses three explicit server-rendered endpoints:

- `GET /portal/draft/new` renders `templates/draft_entry.html`
- `POST /portal/draft` validates required inputs before any draft is saved
- `GET /portal/review/{draft_id}` renders `templates/review_summary.html`

When `POST /portal/draft` is missing required fields, the service returns HTTP 400
and renders `templates/validation_feedback.html` instead of redirecting. The entry,
validation, and review states are intentionally separate templates so the route
contract stays explicit and testable.

### Current manager review path

- The workflow portal persists a submitted request into a manager review queue at
  `/portal/manager/reviews`.
- Each queue item has a detail view at `/portal/manager/reviews/{review_id}`
  that shows current policy posture, approval triggers, policy issues, and the
  immutable approval history recorded on the trip.
- Managers can record `approve`, `request_changes`, or `reject` decisions with
  rationale from the detail view, and the runtime keeps that decision history in
  durable in-memory workflow state for later review during the same service run.

## Expense (Stage 2)

Collecting Receipts → Employee Submit → Manager Review → Accounting Review
→ Reimbursed

Branches: Missing Receipt, Policy Warning (manager override allowed), Reject.

### Expense portal contract

The Stage 2 browser portal now exposes a separate expense and reimbursement flow:

- `GET /portal/expenses/new` renders `templates/portal_expense.html`
- `POST /portal/expenses/review` validates the current expense submission and saves a draft when the required fields are present
- `GET /portal/expenses/{draft_id}` renders the linked receipt, manager/accounting disposition, and accounting export handoff

The expense portal intentionally reuses the existing approval and export services. It does not write directly into an external reimbursement or ERP system yet.
