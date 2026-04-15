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

## Expense (Stage 2)

Collecting Receipts → Employee Submit → Manager Review → Accounting Review
→ Reimbursed

Branches: Missing Receipt, Policy Warning (manager override allowed), Reject.
