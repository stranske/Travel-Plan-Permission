# Validation rule reference

The policy-lite validator is configured through `config/policy.yaml`. Each rule can be tuned or disabled by editing the values under `rules:` and then reloading the `PolicyEngine` (for example via `PolicyEngine.from_file()` or `PolicyEngine.from_yaml()`). Thresholds and severities shown below reflect the repository defaults.

## Rule catalog

| Rule ID | Default severity | Configuration keys | Behavior summary |
| --- | --- | --- | --- |
| `advance_booking` | `advisory` | `days_required` (int) | Warns when the trip is booked fewer than the required days before departure. |
| `fare_comparison` | `blocking` | `max_over_lowest` (decimal) | Blocks when the selected fare exceeds the lowest available by more than the threshold. |
| `cabin_class` | `blocking` | `long_haul_hours` (float), `allowed_classes` (list of strings) | Blocks when a sub-threshold flight duration uses a cabin class outside the allowed list. |
| `fare_evidence` | `blocking` | — | Blocks when fare evidence (e.g., screenshot) is missing. |
| `driving_vs_flying` | `advisory` | — | Warns when driving costs more than the equivalent flight. |
| `hotel_comparison` | `advisory` | `minimum_alternatives` (int) | Warns when fewer than the required number of alternative hotel quotes are provided. |
| `local_overnight` | `advisory` | `min_distance_miles` (float) | Warns when an overnight stay is requested within the local distance threshold. |
| `meal_per_diem` | `advisory` | — | Warns when a per diem is requested while meals are provided by a conference/event. |
| `non_reimbursable` | `blocking` | `blocked_keywords` (list of strings) | Blocks expenses that match non-reimbursable keywords (e.g., liquor, personal). |
| `third_party_paid` | `blocking` | — | Blocks when third-party paid items are not itemized and excluded from reimbursement. |

## Default configuration

```yaml
rules:
  advance_booking:
    days_required: 14
    severity: advisory
  fare_comparison:
    max_over_lowest: 200
    severity: blocking
  cabin_class:
    long_haul_hours: 5
    allowed_classes:
      - economy
    severity: blocking
  fare_evidence:
    severity: blocking
  driving_vs_flying:
    severity: advisory
  hotel_comparison:
    minimum_alternatives: 2
    severity: advisory
  local_overnight:
    min_distance_miles: 50
    severity: advisory
  meal_per_diem:
    severity: advisory
  non_reimbursable:
    blocked_keywords:
      - liquor
      - alcohol
      - personal
    severity: blocking
  third_party_paid:
    severity: blocking
```

### Notes

- To change severity, set `severity` to `blocking` or `advisory`. Blocking results will prevent submission when the rule fails; advisory results allow submission but are surfaced as warnings.
- All rules are loaded automatically by `PolicyEngine.from_file()`; callers can provide inline YAML with `from_yaml()` for scenario-specific testing.
- Messages returned by each rule include the configured threshold values so downstream UIs can present actionable guidance without duplicating configuration.
