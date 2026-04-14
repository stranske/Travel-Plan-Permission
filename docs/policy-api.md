# Policy API

This document describes the stable policy API surface in
`src/travel_plan_permission/policy_api.py` for use by the LangGraph
orchestration layer and planner-facing integrations.

For the operator-facing live-test procedure for these endpoints, including
environment bootstrap and the blessed smoke workflow, see the
[`Planner Live-Test Runbook`](./planner-live-test-runbook.md).

## Data Models

### TripPlan (input)

Example JSON structure (matches `TripPlan` in
`src/travel_plan_permission/models.py`):

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

### PlannerPolicySnapshotRequest (input)

Example JSON structure for planner-facing policy snapshot fetches:

```json
{
  "trip_id": "TRIP-PLANNER-2001",
  "requested_at": "2026-04-11T05:05:00Z",
  "snapshot_generated_at": "2026-04-11T04:30:00Z",
  "known_policy_version": "d7a6d25a",
  "invalidate_reason": null
}
```

### PlannerPolicySnapshot (output)

Example JSON structure for the planner-facing policy snapshot contract:

```json
{
  "trip_id": "TRIP-PLANNER-2001",
  "freshness": "current",
  "generated_at": "2026-04-11T05:05:00Z",
  "expires_at": "2026-04-12T05:05:00Z",
  "invalidated_at": null,
  "invalidation_reason": null,
  "policy_status": "fail",
  "booking_requirements": [
    {
      "code": "advance_booking",
      "summary": "Bookings must be made 14 days before departure.",
      "severity": "warning"
    }
  ],
  "documentation_rules": [
    {
      "code": "fare_evidence",
      "summary": "Screenshot or fare evidence must be attached to the request.",
      "severity": "error"
    }
  ],
  "approval_triggers": [
    {
      "code": "fare_evidence",
      "summary": "Screenshot or fare evidence must be attached to the request.",
      "blocking": true,
      "source": "policy_rule"
    }
  ],
  "auth": {
    "endpoint": "GET /api/planner/policy-snapshot",
    "required_permission": "view",
    "auth_scheme": "Bearer token with SSO-backed access token",
    "supported_sso": ["azure_ad", "okta", "google"]
  },
  "versioning": {
    "contract_version": "2026-04-11",
    "policy_version": "d7a6d25a",
    "planner_known_policy_version": "d7a6d25a",
    "compatible_with_planner_cache": true,
    "etag": "TRIP-PLANNER-2001:d7a6d25a:2026-04-11:5f2e7c1a9b3d"
  }
}
```

### PlannerProposalSubmissionRequest (input)

Example JSON structure for planner proposal submission:

```json
{
  "trip_id": "TRIP-1001",
  "proposal_id": "proposal-123",
  "proposal_version": "proposal-v1",
  "payload": {
    "selected_options": ["flight-1", "hotel-3"],
    "submission_mode": "queue"
  },
  "request_id": "req-submit-001",
  "correlation_id": {
    "value": "corr-submit-001",
    "issued_by": "trip-planner"
  },
  "transport_pattern": "deferred",
  "organization_id": "org-acme",
  "submitted_at": "2026-04-11T12:30:00Z",
  "service_available": true
}
```

### PlannerProposalOperationResponse (output)

Example JSON structure for proposal submission or status polling:

```json
{
  "operation": "submit_proposal",
  "submission_status": "pending",
  "request_id": "req-submit-001",
  "correlation_id": {
    "value": "corr-submit-001",
    "issued_by": "trip-planner"
  },
  "transport_pattern": "deferred",
  "execution_status": {
    "state": "deferred",
    "terminal": false,
    "summary": "Proposal queued for evaluation.",
    "external_status": "202 Accepted",
    "poll_after_seconds": 30,
    "updated_at": "2026-04-11T12:30:00Z"
  },
  "result_payload": {
    "trip_id": "TRIP-1001",
    "proposal_id": "proposal-123",
    "proposal_version": "proposal-v1",
    "execution_id": "exec-10c6fb4730f2",
    "queue_state": "waiting_for_policy_engine",
    "result_endpoint": "GET /api/planner/executions/exec-10c6fb4730f2/evaluation-result",
    "organization_id": "org-acme",
    "submitted_payload_keys": ["selected_options", "submission_mode"]
  },
  "error": null,
  "retry": {
    "attempt": 0,
    "max_attempts": 5,
    "retryable": true,
    "backoff_seconds": 30,
    "next_retry_at": "2026-04-11T12:30:30Z",
    "reason": "Await planner-side evaluation completion before retrying."
  },
  "received_at": "2026-04-11T12:30:00Z",
  "status_endpoint": "GET /api/planner/proposals/proposal-123/executions/exec-10c6fb4730f2"
}
```

For the full planner-facing transport, versioning, and fixture contract, see
[`docs/contracts/planner-integration.md`](./contracts/planner-integration.md).

For live HTTP testing, the runtime must also supply
`TPP_ACCESS_TOKEN_SUBJECT` and `TPP_ACCESS_TOKEN_ROLE` alongside the bearer
token so the service can authorize planner endpoints through the published
permission model.

### PlannerProposalEvaluationResult (output)

Example JSON structure for planner-facing evaluation results:

```json
{
  "trip_id": "TRIP-1001",
  "proposal_id": "proposal-123",
  "proposal_version": "proposal-v1",
  "execution_id": "exec-10c6fb4730f2",
  "request_id": "req-eval-001",
  "correlation_id": {
    "value": "corr-submit-001",
    "issued_by": "trip-planner"
  },
  "outcome": "non_compliant",
  "result_endpoint": "GET /api/planner/executions/exec-10c6fb4730f2/evaluation-result",
  "status_endpoint": "GET /api/planner/proposals/proposal-123/executions/exec-10c6fb4730f2",
  "policy_result": {
    "status": "fail",
    "issues": [
      {
        "code": "fare_comparison",
        "message": "Selected fare exceeds the lowest comparable fare threshold.",
        "severity": "error",
        "context": {
          "rule_id": "fare_comparison",
          "severity": "blocking"
        }
      }
    ],
    "policy_version": "b6a28d5d9a30e4f6f7710c7d4cdcaef1c45df3449500f12d822d29fc2bc4dd39"
  },
  "blocking_issues": [
    {
      "code": "fare_comparison",
      "message": "Selected fare exceeds the lowest comparable fare threshold.",
      "field_path": "selected_fare",
      "resolution": "Choose a fare that meets the lowest-fare guidance or request an exception."
    }
  ],
  "preferred_alternatives": [
    {
      "category": "airfare",
      "title": "Use the lower comparable airfare",
      "rationale": "Current airfare from Blue Skies Airlines exceeds the lowest comparable fare.",
      "suggested_value": "300.00"
    }
  ],
  "exception_requirements": [],
  "reoptimization_guidance": [
    {
      "code": "lower_trip_cost",
      "summary": "Reprice airfare and keep the selected fare within the lowest-fare threshold.",
      "actions": [
        "Refresh available airfare options.",
        "Choose a fare that matches or improves on the lowest comparable fare."
      ]
    }
  ],
  "generated_at": "2026-04-11T12:31:00Z"
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

### get_policy_snapshot

**Signature**

```python
def get_policy_snapshot(
    plan: TripPlan,
    request: PlannerPolicySnapshotRequest | None = None,
) -> PlannerPolicySnapshot:
    ...
```

**Description**

Returns a planner-facing snapshot contract built from the current policy,
approval-rule, and provider-registry source of truth. The response packages
booking requirements, documentation rules, approval triggers, auth guidance,
and version metadata without requiring the planner to understand internal rule
objects.

**Freshness states**

- `current`: snapshot still within the 24-hour TTL
- `stale`: snapshot TTL expired and should be refreshed before planner reuse
- `invalidated`: the caller explicitly invalidated its cached snapshot

**Authentication and versioning guidance for `trip-planner`**

- Call the seam as `GET /api/planner/policy-snapshot`.
- Access requires the `view` permission from the security model.
- The expected auth scheme is a bearer token validated against one of the
  configured auth modes:
  - `static-token` using `TPP_ACCESS_TOKEN`
  - `bootstrap-token` using short-lived tokens minted by
    `tpp-planner-token` and validated against
    `TPP_BOOTSTRAP_SIGNING_SECRET`
- The configured provider must still be one of `azure_ad`, `okta`, or `google`.
- Cache the response by `versioning.etag` and invalidate local planner guidance
  when `versioning.compatible_with_planner_cache` is `false`.
- The canonical request/response examples for this seam live in
  `tests/fixtures/planner_integration/`.
- The source-of-truth live operator path for these endpoints lives in
  [`docs/planner-live-test-runbook.md`](./planner-live-test-runbook.md).

**Planner handshake**

1. Fetch a policy snapshot before presenting provider or documentation
   constraints in the planner UI.
2. Submit the proposal using the canonical `TripPlan` shape with
   `status="submitted"` and planner-selected providers populated.
3. Read proposal status back using the same `TripPlan` shape, including
   `approval_history` and any current `validation_results`.
4. Use `PolicyCheckResult` as the machine-readable evaluation response for
   planner follow-up handling.

**Example**

```python
from travel_plan_permission.policy_api import (
    PlannerPolicySnapshotRequest,
    get_policy_snapshot,
)

request = PlannerPolicySnapshotRequest(
    trip_id=plan.trip_id,
    known_policy_version="d7a6d25a",
)

snapshot = get_policy_snapshot(plan, request)
assert snapshot.freshness == "current"
```

Stale snapshot:

```python
request = PlannerPolicySnapshotRequest(
    trip_id=plan.trip_id,
    requested_at=datetime(2026, 4, 12, 12, 0, tzinfo=UTC),
    snapshot_generated_at=datetime(2026, 4, 11, 11, 0, tzinfo=UTC),
)
snapshot = get_policy_snapshot(plan, request)
assert snapshot.freshness == "stale"
```

Invalidated snapshot:

```python
request = PlannerPolicySnapshotRequest(
    trip_id=plan.trip_id,
    known_policy_version="outdated-version",
    invalidate_reason="policy rules rotated after planner cache warmup",
)
snapshot = get_policy_snapshot(plan, request)
assert snapshot.freshness == "invalidated"
```

### submit_proposal

**Signature**

```python
def submit_proposal(
    plan: TripPlan,
    request: PlannerProposalSubmissionRequest,
) -> PlannerProposalOperationResponse:
    ...
```

**Description**

Builds the planner-facing submission contract for proposal execution. The
response mirrors the downstream `trip-planner` transport vocabulary:
correlation IDs, execution IDs, retry guidance, and stable status/result
endpoints are all emitted in a single deterministic envelope.

**Submission states**

- `pending`: the proposal was accepted and queued or is still running.
- `succeeded`: the current trip state already reflects a completed execution.
- `failed`: the proposal is in a rejected state and needs planner remediation.
- `unavailable`: the planner-facing transport seam is unavailable; retry later.

**Example**

```python
from datetime import UTC, datetime

from travel_plan_permission.policy_api import (
    PlannerProposalSubmissionRequest,
    submit_proposal,
)

request = PlannerProposalSubmissionRequest(
    trip_id=plan.trip_id,
    proposal_id="proposal-123",
    proposal_version="proposal-v1",
    payload={"selected_options": ["flight-1", "hotel-3"]},
    submitted_at=datetime(2026, 4, 11, 12, 30, tzinfo=UTC),
)

response = submit_proposal(plan, request)
print(response.submission_status)
print(response.result_payload["execution_id"])
```

### poll_execution_status

**Signature**

```python
def poll_execution_status(
    plan: TripPlan,
    request: PlannerProposalStatusRequest,
) -> PlannerProposalOperationResponse:
    ...
```

**Description**

Returns the stable planner-facing execution-status contract for a previously
submitted proposal. Polling uses the deterministic execution ID and preserves
the same correlation semantics as the submission call so `trip-planner` can
persist and replay the lane cleanly.

**Example**

```python
from datetime import UTC, datetime

from travel_plan_permission.policy_api import (
    PlannerProposalStatusRequest,
    poll_execution_status,
)

status_request = PlannerProposalStatusRequest(
    trip_id=plan.trip_id,
    proposal_id="proposal-123",
    proposal_version="proposal-v1",
    execution_id=response.result_payload["execution_id"],
    requested_at=datetime(2026, 4, 11, 12, 31, tzinfo=UTC),
)

status = poll_execution_status(plan, status_request)
print(status.execution_status.state if status.execution_status else "unavailable")
```

### get_evaluation_result

**Signature**

```python
def get_evaluation_result(
    plan: TripPlan,
    request: PlannerProposalEvaluationRequest,
) -> PlannerProposalEvaluationResult:
    ...
```

**Description**

Returns the planner-facing evaluation result payload keyed to the same stable
proposal/execution linkage used by `submit_proposal` and
`poll_execution_status`. The response distinguishes compliant,
non-compliant, and exception-required outcomes while publishing blocking issue
detail, preferred alternatives, and deterministic reoptimization guidance.

**Example**

```python
from datetime import UTC, datetime

from travel_plan_permission.policy_api import (
    PlannerProposalEvaluationRequest,
    get_evaluation_result,
)

evaluation_request = PlannerProposalEvaluationRequest(
    trip_id=plan.trip_id,
    proposal_id="proposal-123",
    proposal_version="proposal-v1",
    execution_id=response.result_payload["execution_id"],
    requested_at=datetime(2026, 4, 11, 12, 31, tzinfo=UTC),
)

evaluation = get_evaluation_result(plan, evaluation_request)
print(evaluation.outcome)
print(evaluation.result_endpoint)
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
from datetime import date
from pathlib import Path
from travel_plan_permission.models import TripPlan
from travel_plan_permission.policy_api import (
    PlannerPolicySnapshotRequest,
    check_trip_plan,
    fill_travel_spreadsheet,
    get_policy_snapshot,
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
snapshot = get_policy_snapshot(plan, PlannerPolicySnapshotRequest(trip_id=plan.trip_id))
spreadsheet_path = fill_travel_spreadsheet(plan, Path("./request.xlsx"))
reconciliation = reconcile(plan, [])
```

## Error Handling and Edge Cases

- `check_trip_plan` returns a `pass` status when no blocking issues are raised.
  Advisory-only results are reported as `warning` severity issues.
- `list_allowed_vendors` returns an empty list when the provider registry has no
  matching entries for the destination or date.
- `get_policy_snapshot` returns `current`, `stale`, or `invalidated` based on
  request freshness and explicit invalidation input.
- `get_policy_snapshot` expects `trip-planner` to refresh when
  `versioning.compatible_with_planner_cache` is `false`.
- `fill_travel_spreadsheet` raises `FileNotFoundError` if the template cannot be
  located, and may raise `openpyxl` errors for malformed templates.
- `fill_travel_spreadsheet` writes to the filesystem; ensure the output
  directory exists and is writable to avoid `OSError` or permission errors.
- `reconcile` assumes receipts are valid; `Receipt` validation raises
  `ValueError` for unsupported file types or oversized uploads.
- `reconcile` returns `under_budget`, `on_budget`, or `over_budget` based on the
  variance between planned and actual totals.
