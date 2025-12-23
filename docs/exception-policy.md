# Exception handling for policy-lite advisories

Exception handling provides a structured way to document and route requests that need to bypass advisory policy-lite rules. Travelers can attach exception requests directly to a trip plan; each request records the requested type, justification, and supporting documentation, and then flows through approval with clear escalation.

## Exception types

Exception types mirror the policy-lite advisory rules to keep taxonomy aligned with enforcement:

- `advance_booking`
- `driving_vs_flying`
- `hotel_comparison`
- `local_overnight`
- `meal_per_diem`

When the policy configuration adds or removes advisory rules, update the enum to stay in sync.

## Request requirements

- **Justification**: must be at least 50 characters to ensure context for reviewers.
- **Supporting docs**: optional list of URLs or file references.
- **Amount**: optional financial impact to drive routing.

## Approval routing

Routing defaults to the lowest approval level for the exception type, then escalates based on the amount:

- Base levels: `advance_booking`, `driving_vs_flying`, `hotel_comparison`, and `meal_per_diem` start at **manager**; `local_overnight` starts at **director**.
- Amount thresholds:
  - ≥ 5,000 routes to at least **director**.
  - ≥ 20,000 routes to **board**.

`determine_exception_approval_level` computes the correct starting level using the type and amount provided.

## Escalation and tracking

- Pending requests escalate to the next approval level after **48 hours**. The escalation timestamp is recorded and status moves to `escalated`.
- Approvals capture the approver, approval level, timestamp, and optional notes to maintain an audit trail.

## Reporting

Use `build_exception_dashboard` to generate pattern summaries for dashboards:

- `by_type`: counts by exception type
- `by_requestor`: counts by requester
- `by_approver`: counts completed approvals by approver
