# Workflows (Lite)

## Itinerary (Stage 1–2)

Draft → Employee Submit → Manager Review → Board Secretary Review → Approved
→ Ready to Travel

Branches: Request Changes, Reject. No delegation/escalation in Stage 1–2.

Current local portal/runtime support now persists the submitted manager-review queue to a
file-backed workflow store, exposes a manager queue/detail surface under `/portal/manager/reviews`,
and records rationale-backed approve/request-changes/reject decisions against the request.

## Expense (Stage 2)

Collecting Receipts → Employee Submit → Manager Review → Accounting Review
→ Reimbursed

Branches: Missing Receipt, Policy Warning (manager override allowed), Reject.
