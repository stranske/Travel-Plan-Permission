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

## Approval permission vs. tier entitlement

Two distinct things gate an exception decision, and holding the first never implies the second:

1. **Generic approval permission** (`Permission.APPROVE`) — the endpoint-level check that lets a
   caller reach the decision route at all. On its own it covers the **manager** tier only.
2. **Exception-tier entitlement** — an explicit allow-list binding an authenticated subject to the
   highest routed level it may decide. **Director** and **board** requests require it.

The routed level enforced at decision time is the higher of the request's stored `approval_level`
(which carries any 48-hour escalation) and the level re-derived from its own type and amount, so a
stale or under-stated stored value can never lower the authority required. Request-supplied fields
— the `actor_role` query parameter, a posted `actor_id` — are never treated as authority; only the
authenticated subject is. A caller without sufficient entitlement receives `403` and the request's
status and approval history are left untouched; the denial is recorded in the audit trail with the
required and granted levels.

### Deployment responsibility

Entitlements are configuration, not code. Set `TPP_EXCEPTION_TIER_ENTITLEMENTS` to a JSON object
mapping subject to its highest approvable level:

```json
{"director@example.org": "director", "board-chair@example.org": "board"}
```

**The shipped default is empty and fails closed**: until a deployment supplies real principals, no
subject can finalize a director- or board-level exception. Mapping actual people to these tiers is
an organizational decision and is deliberately left unconfigured in this repository — the test
suite uses synthetic subjects only. An unparseable value makes the decision route return `503`
rather than silently falling back to an empty map.

## Escalation and tracking

- Pending requests escalate to the next approval level after **48 hours**. The escalation timestamp is recorded and status moves to `escalated`.
- Approvals capture the approver, approval level, timestamp, and optional notes to maintain an audit trail.

## Reporting

Use `build_exception_dashboard` to generate pattern summaries for dashboards:

- `by_type`: counts by exception type
- `by_requestor`: counts by requester
- `by_approver`: counts completed approvals by approver

## Current portal workflow

The current shipped portal/admin surface supports a bounded exception loop:

- Travelers can attach an exception request from the draft review summary before or after submission.
- Review-capable roles can inspect pending exceptions from `/portal/admin` and from the manager review detail page.
- Approve-capable roles can record approve/reject decisions, and those actions are reflected in the runtime audit trail, including any supplied notes. Decisions above the manager tier additionally require the deciding subject to hold the matching exception-tier entitlement described above.

This is intentionally narrower than a full enterprise exception-management platform. Bulk workflow routing, durable inboxes, and downstream reimbursement settlement handling remain later work.
