# Validation rules (policy-lite)

These rules are configured via `config/policy.yaml` and loaded by `PolicyEngine.from_file()` or `PolicyEngine.from_yaml()`. Each rule produces a structured result with `rule_id`, `severity` (`blocking` or `advisory`), `passed`, and `message`. The descriptions below reflect the default configuration shipped with the repo.

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
