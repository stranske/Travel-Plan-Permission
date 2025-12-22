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
