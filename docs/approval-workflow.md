# Approval workflow examples

The approval engine evaluates expenses against configurable rules defined in YAML.

## Default rules

The repository ships with default rules in `config/approval_rules.yaml`:

- `default_under_100`: Auto-approve any expense at or below $100.
- `high_amount_flag`: Flag expenses at or above $5000 for manager review.
- `meals_manager_review`: Require manager approval for meal expenses at or above $300.

Rules are processed in order, allowing category-specific entries to override general thresholds.

## Configuring rules

- **File-based:** Update `config/approval_rules.yaml` to change thresholds or add new rule blocks.
- **Environment-based:** Provide YAML via the `APPROVAL_RULES` environment variable to override file-based configuration.

Example environment configuration:

```bash
export APPROVAL_RULES="
rules:
  - name: taxi_fast_track
    category: ground_transport
    threshold: 75
    action: auto_approve
    approver: travel_ops
"
```

## Using the engine

```python
from travel_plan_permission.approval import ApprovalEngine
from travel_plan_permission.models import ExpenseItem, ExpenseCategory
from decimal import Decimal
from datetime import date

engine = ApprovalEngine.from_file()
expense = ExpenseItem(
    category=ExpenseCategory.MEALS,
    description="Team dinner",
    amount=Decimal("350.00"),
    expense_date=date(2025, 1, 1),
)

decision = engine.evaluate_expense(expense)
print(decision.status)  # ApprovalStatus.FLAGGED
```

## Approval packets and notifications

Approval packets package the trip summary, policy status, cost breakdown, and a PDF attachment for multi-level reviewers.

- Manager email template includes trip summary, total cost, compliance status, and approve/reject/override links.
- Board email template mirrors the manager copy but highlights the audit-ready approval history.
- The PDF generator creates a single-page packet for routine trips and introduces additional pages when cost or history entries exceed the configured threshold (default: 15 rows).

### Data model

- `ApprovalPacket` bundles the rendered emails, PDF bytes, and immutable `approval_history`.
- `ApprovalLinks` supply approve/reject/override URLs for both manager and board audiences.
- `TripPlan.approval_history` is append-only. Each `ApprovalEvent` captures approver ID, level (manager/board), outcome, timestamp, prior status, and resulting status.
- `review_workflow.py` adds persisted in-runtime `ReviewRequest` state for manager queue/detail
  screens. It keeps the queue status, submission timestamp, policy posture, and a
  workflow event log alongside the immutable `TripPlan.approval_history`.

### Override and auditability rules

- `TripPlan.record_approval_decision` enforces justification text for override outcomes.
- Approval history entries are frozen Pydantic models and stored as tuples to prevent mutation.
- PDFs include the justification column to preserve override rationale for auditing.
- Manager review decisions captured through the browser queue require rationale so
  approval, rejection, and requested changes all leave an audit-ready explanation.

## Portal surface design

The portal should separate reviewer-facing product work from administrator and
developer diagnostics:

- **Reviewer surfaces** should answer what request is being reviewed, whether it
  is ready to approve, what exception or follow-up is required, and what action
  the reviewer can take next. They should use business-language labels rather
  than planner transport details, payload IDs, or policy-engine internals.
- **Administrator surfaces** should expose policy configuration, thresholds,
  approval-routing rules, user/role setup, and operational status needed to run
  the approval program.
- **Developer/debug surfaces** should preserve raw planner payloads, proposal
  IDs, execution IDs, policy versions, queue states, polling outcomes, and
  validation traces for diagnosis. These details should remain available, but
  they should not be required for routine manager review.

When TPP is used from `trip-planner`, `trip-planner` decides whether policy
readiness is relevant to a given trip. TPP remains responsible for making the
actual approval review legible once a business proposal reaches the portal.
