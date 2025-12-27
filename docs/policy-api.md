# Policy API

This document describes the stable policy API surface in
`src/travel_plan_permission/policy_api.py` for use by the LangGraph
orchestration layer.

## Data Models

### TripPlan (input)

Example JSON structure (matches `TripPlan` in `src/travel_plan_permission/models.py`):

```json
{
  "trip_id": "TRIP-1001",
  "traveler_name": "Alex Rivera",
  "traveler_role": "Senior Analyst",
  "department": "Finance",
  "destination": "Chicago, IL 60601",
  "origin_city": "Austin, TX",
  "destination_city": "Chicago, IL",
  "departure_date": "2025-06-10",
  "return_date": "2025-06-12",
  "purpose": "Quarterly planning summit",
  "transportation_mode": "air",
  "expected_costs": {
    "airfare": 420.50,
    "lodging": 600.00
  },
  "funding_source": "FIN-OPS",
  "estimated_cost": 1200.50,
  "status": "submitted",
  "expense_breakdown": {
    "airfare": 420.50,
    "lodging": 600.00,
    "meals": 180.00
  },
  "selected_providers": {
    "airfare": "Skyway Air",
    "lodging": "Lakeside Hotel"
  },
  "validation_results": [],
  "approval_history": [],
  "exception_requests": []
}
```

### PolicyCheckResult (output)

Example JSON structure (matches `PolicyCheckResult` in
`src/travel_plan_permission/policy_api.py`):

```json
{
  "status": "fail",
  "issues": [
    {
      "code": "advance_booking",
      "message": "Flights must be booked 14 days in advance",
      "severity": "warning",
      "context": {
        "rule_id": "advance_booking",
        "severity": "advisory"
      }
    }
  ],
  "policy_version": "d7a6d25a"
}
```

## Functions

### check_trip_plan

**Signature**

```python
def check_trip_plan(plan: TripPlan) -> PolicyCheckResult:
    ...
```

**Description**

Evaluates a `TripPlan` using the policy-lite engine and returns aggregated
results with a deterministic policy version identifier.

**Parameters**

- `plan`: `TripPlan` instance containing trip details and planned costs.

**Returns**

- `PolicyCheckResult` with pass/fail status, any issues, and the policy version.

**Example**

```python
from travel_plan_permission.models import TripPlan
from travel_plan_permission.policy_api import check_trip_plan

plan = TripPlan(
    trip_id="TRIP-1001",
    traveler_name="Alex Rivera",
    destination="Chicago, IL 60601",
    departure_date="2025-06-10",
    return_date="2025-06-12",
    purpose="Quarterly planning summit",
    estimated_cost=1200.50,
    expense_breakdown={"airfare": 420.50, "lodging": 600.00, "meals": 180.00},
)

result = check_trip_plan(plan)
print(result.status)
print(result.policy_version)
```

### list_allowed_vendors

**Signature**

```python
def list_allowed_vendors(plan: TripPlan) -> list[str]:
    ...
```

**Description**

Returns the approved vendors for the trip destination and departure date,
combining all provider types in the registry.

**Parameters**

- `plan`: `TripPlan` containing destination and dates used to lookup providers.

**Returns**

- Sorted list of provider names. Returns an empty list if no providers match.

**Example**

```python
from travel_plan_permission.models import TripPlan
from travel_plan_permission.policy_api import list_allowed_vendors

plan = TripPlan(
    trip_id="TRIP-1002",
    traveler_name="Morgan Lee",
    destination="Seattle, WA 98101",
    departure_date="2025-07-15",
    return_date="2025-07-18",
    purpose="Partner meetings",
    estimated_cost=980.00,
)

vendors = list_allowed_vendors(plan)
print(vendors)
```

### fill_travel_spreadsheet

**Signature**

```python
def fill_travel_spreadsheet(plan: TripPlan, output_path: Path) -> Path:
    ...
```

**Description**

Fills the travel request spreadsheet template using a `TripPlan` and writes the
result to `output_path`. The template is loaded from `templates/` using the
mapping in `config/`.

**Parameters**

- `plan`: `TripPlan` used to populate template fields.
- `output_path`: filesystem path to write the completed spreadsheet.

**Returns**

- `Path` to the written spreadsheet file.

**Example**

```python
from pathlib import Path
from travel_plan_permission.models import TripPlan
from travel_plan_permission.policy_api import fill_travel_spreadsheet

plan = TripPlan(
    trip_id="TRIP-1003",
    traveler_name="Riley Chen",
    destination="Denver, CO 80202",
    departure_date="2025-09-03",
    return_date="2025-09-06",
    purpose="Client on-site",
    estimated_cost=1450.00,
    expense_breakdown={"airfare": 380.00, "lodging": 780.00},
)

output = fill_travel_spreadsheet(plan, Path("./travel_request.xlsx"))
print(output)
```

### reconcile

**Signature**

```python
def reconcile(plan: TripPlan, receipts: list[Receipt]) -> ReconciliationResult:
    ...
```

**Description**

Builds an expense report from receipt data and compares actual spend against the
planned trip total. Returns a reconciliation summary with variance.

**Parameters**

- `plan`: `TripPlan` with estimated cost.
- `receipts`: list of `Receipt` metadata objects.

**Returns**

- `ReconciliationResult` with totals, variance, and receipt summary stats.

**Example**

```python
from datetime import date
from decimal import Decimal

from travel_plan_permission.models import TripPlan
from travel_plan_permission.policy_api import reconcile
from travel_plan_permission.receipts import Receipt

plan = TripPlan(
    trip_id="TRIP-1004",
    traveler_name="Sam Patel",
    destination="Boston, MA 02108",
    departure_date="2025-05-20",
    return_date="2025-05-22",
    purpose="Training",
    estimated_cost=900.00,
)

receipts = [
    Receipt(
        total=Decimal("280.00"),
        date=date(2025, 5, 20),
        vendor="Harbor Hotel",
        file_reference="receipts/hotel.pdf",
        file_size_bytes=120_000,
    ),
    Receipt(
        total=Decimal("45.25"),
        date=date(2025, 5, 21),
        vendor="Cafe Luna",
        file_reference="receipts/meal.png",
        file_size_bytes=80_000,
    ),
]

result = reconcile(plan, receipts)
print(result.status)
print(result.actual_total)
```

Example output (JSON):

```json
{
  "trip_id": "TRIP-1004",
  "report_id": "TRIP-1004-reconciliation",
  "planned_total": 900.00,
  "actual_total": 325.25,
  "variance": -574.75,
  "status": "under_budget",
  "receipt_count": 2,
  "receipts_by_type": {
    ".pdf": 1,
    ".png": 1
  },
  "expenses_by_category": {
    "other": 325.25
  }
}
```

## Typical Usage Patterns

```python
from pathlib import Path
from travel_plan_permission.models import TripPlan
from travel_plan_permission.policy_api import (
    check_trip_plan,
    fill_travel_spreadsheet,
    list_allowed_vendors,
    reconcile,
)

plan = TripPlan(
    trip_id="TRIP-1005",
    traveler_name="Jamie Park",
    destination="New York, NY 10001",
    departure_date="2025-08-12",
    return_date="2025-08-15",
    purpose="Client briefing",
    estimated_cost=1350.00,
    expense_breakdown={"airfare": 500.00, "lodging": 650.00},
)

policy_result = check_trip_plan(plan)
allowed_vendors = list_allowed_vendors(plan)
spreadsheet_path = fill_travel_spreadsheet(plan, Path("./request.xlsx"))
reconciliation = reconcile(plan, [])
```

## Error Handling and Edge Cases

- `check_trip_plan` returns a `pass` status when no blocking issues are raised.
  Advisory-only results are reported as `warning` severity issues.
- `list_allowed_vendors` returns an empty list when the provider registry has no
  matching entries for the destination or date.
- `fill_travel_spreadsheet` raises `FileNotFoundError` if the template cannot be
  located, and may raise `openpyxl` errors for malformed templates.
- `fill_travel_spreadsheet` writes to the filesystem; ensure the output directory
  exists and is writable to avoid `OSError` or permission errors.
- `reconcile` assumes receipts are valid; `Receipt` validation raises
  `ValueError` for unsupported file types or oversized uploads.
- `reconcile` returns `under_budget`, `on_budget`, or `over_budget` based on the
  variance between planned and actual totals.
