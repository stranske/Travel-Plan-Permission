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

### Override and auditability rules

- `TripPlan.record_approval_decision` enforces justification text for override outcomes.
- Approval history entries are frozen Pydantic models and stored as tuples to prevent mutation.
- PDFs include the justification column to preserve override rationale for auditing.
