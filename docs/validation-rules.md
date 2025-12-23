# Validation Rules

This document describes the two validation systems available for trip plans and expenses.

---

## Trip Plan Validation (PolicyValidator)

The `PolicyValidator` validates `TripPlan` objects against configurable business rules before submission. Rules are configured via `config/validation.yaml` and loaded by `PolicyValidator.from_file()`.

### Usage

```python
from travel_plan_permission.models import TripPlan
from travel_plan_permission.validation import PolicyValidator

# Validate using default rules from config/validation.yaml
plan = TripPlan(...)
results = plan.run_validation()

# Or use a custom validator
validator = PolicyValidator.from_file("custom_rules.yaml")
results = plan.run_validation(validator=validator)

# Check for blocking violations
blocking_errors = [r for r in results if r.is_blocking]
```

### ValidationResult Structure

Each validation result contains:
- `code` - Stable identifier (e.g., "ADV-001")
- `message` - Human-readable explanation
- `severity` - One of: `error`, `warning`, `info`
- `rule_name` - Name of the rule that produced the result
- `blocking` - Whether the violation prevents submission
- `is_blocking` - Property that returns `True` when `blocking=True` AND `severity=error`

### Available Rules

| Rule Type | Configuration Keys | Behavior |
| --- | --- | --- |
| `advance_booking` | `min_days_domestic`, `min_days_international`, `international_destinations` | Require advance notice for trip bookings. Domestic and international trips can have different thresholds. |
| `budget_limit` | `trip_limit`, `category_limits` | Enforce per-trip and per-category spending limits. Category limits are keyed by `ExpenseCategory` values. |
| `duration_limit` | `max_consecutive_days` | Restrict maximum consecutive travel days. |

### Configuration Example (config/validation.yaml)

```yaml
rules:
  - type: advance_booking
    name: default_advance_booking
    code: ADV-001
    severity: error
    blocking: true
    min_days_domestic: 7
    min_days_international: 14
    international_destinations:
      - international
      - overseas

  - type: budget_limit
    name: default_budget_limit
    code: BUD-001
    severity: error
    blocking: true
    trip_limit: 5000
    category_limits:
      lodging: 2500
      meals: 800

  - type: duration_limit
    name: default_duration_limit
    code: DUR-001
    severity: warning
    blocking: false
    max_consecutive_days: 14
```

---

## Policy-Lite Rules (PolicyEngine)

The `PolicyEngine` evaluates expense and travel policy compliance rules. These rules are configured via `config/policy.yaml` and loaded by `PolicyEngine.from_file()` or `PolicyEngine.from_yaml()`. Each rule produces a structured result with `rule_id`, `severity` (`blocking` or `advisory`), `passed`, and `message`.

### Available Rules

| Rule ID | Default severity | Configuration keys | Behavior |
| --- | --- | --- | --- |
| `advance_booking` | `advisory` | `days_required` | Require bookings be made at least the configured days before departure (default 14). |
| `fare_comparison` | `blocking` | `max_over_lowest` | Selected fare cannot exceed the lowest comparable fare by more than the configured amount (default $200). |
| `cabin_class` | `blocking` | `long_haul_hours`, `allowed_classes` | Flights at or under the long-haul threshold must use one of the allowed cabin classes (default ≤5 hours must be economy). |
| `fare_evidence` | `blocking` | — | A screenshot or other fare evidence must be attached. |
| `driving_vs_flying` | `advisory` | — | Reimbursement is limited to the lesser cost between driving and flying when both estimates are provided. |
| `hotel_comparison` | `advisory` | `minimum_alternatives` | Require at least the configured number of comparable hotel quotes (default 2). |
| `local_overnight` | `advisory` | `min_distance_miles` | Overnight stays within the configured distance from the office need a waiver (default 50 miles). |
| `meal_per_diem` | `advisory` | — | Exclude conference-provided meals from per diem claims. |
| `non_reimbursable` | `blocking` | `blocked_keywords` | Expenses containing the configured keywords are not reimbursable (defaults: liquor, alcohol, personal). |
| `third_party_paid` | `blocking` | — | Third-party paid items must be itemized and excluded from reimbursement. |

Update `config/policy.yaml` to adjust thresholds or severities for your deployment. Rules are evaluated in the order shown above, and `PolicyEngine.blocking_results()` returns only failed blocking rules for submission gating.
