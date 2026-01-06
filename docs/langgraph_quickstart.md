# LangGraph Quickstart

This guide explains how the LangGraph orchestrator should interact with the
TripPlan contract and the policy tooling in this repo.

## Canonical TripPlan contract

The canonical contract is `TripPlan` in `src/travel_plan_permission/models.py`.
All policy APIs (`check_trip_plan`, `list_allowed_vendors`, `reconcile`,
`fill_travel_spreadsheet`) expect this model.

Example payload (matches `TripPlan`):

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
    "airfare": 420.5,
    "lodging": 600.0
  },
  "funding_source": "FIN-OPS",
  "estimated_cost": 1200.5,
  "status": "submitted",
  "expense_breakdown": {
    "airfare": 420.5,
    "lodging": 600.0,
    "meals": 180.0
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

The minimal intake schema (`schemas/trip_plan.min.schema.json`) is a
lightweight payload used for early UI or LLM intake. It is not the canonical
contract; convert it into `TripPlan` before calling policy APIs.

## Conversion process (minimal intake -> TripPlan)

Use `trip_plan_from_minimal` in `src/travel_plan_permission/conversion.py` to
map the minimal JSON schema to the canonical `TripPlan`. This function:

- Builds `destination` from `city_state` + `destination_zip`.
- Maps `business_purpose` to `TripPlan.purpose`.
- Aggregates estimated costs into `expense_breakdown` and `expected_costs`.

Example:

```python
import json
from pathlib import Path

from travel_plan_permission import trip_plan_from_minimal

payload = json.loads(
    Path("tests/fixtures/sample_trip_plan_minimal.json").read_text(encoding="utf-8")
)

plan = trip_plan_from_minimal(
    payload,
    trip_id="TRIP-1001",
    origin_city="Austin, TX",
)
```

## Run the minimal LangGraph flow locally

The minimal LangGraph orchestration is tracked in
`docs/ORCHESTRATION_PLAN.md` (Phase 2). This repo does not ship the
orchestrator, but you can prototype the flow locally by wiring LangGraph to the
policy API in this package.

Steps:

1. Create a virtualenv and install this package:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e .
   ```

2. Install LangGraph in the same environment:

   ```bash
   pip install langgraph
   ```

3. Create a small local script that loads a `TripPlan`, calls
   `check_trip_plan`, and then uses `fill_travel_spreadsheet` for the approved
   path. Use the Phase 2 nodes in `docs/ORCHESTRATION_PLAN.md` as the template
   for the graph shape.

## Artifacts produced

The policy layer returns in-memory data and writes files when explicitly asked:

- `fill_travel_spreadsheet` writes an `.xlsx` file to the path you pass in.
- `build_approval_packet` returns an `ApprovalPacket` containing:
  `pdf_bytes` (bytes) and `EmailContent` (subject/body strings).
- `build_output_bundle` returns in-memory bytes for `itinerary_excel` and
  `summary_pdf`, plus JSON strings for the conversation log.
- `ExportService.to_csv` returns `(filename, csv_text)` as UTF-8 text.
- `ExportService.to_excel` returns `(filename, excel_bytes)` as bytes.
- `ValidationSnapshotStore.append` writes JSON snapshots under
  `snapshots/<trip_id>/` (or `SNAPSHOT_DIR` if set).

## Adding a new LangGraph node safely

1. Keep nodes deterministic: accept a `TripState` input and return a new or
   updated `TripState` without hidden side effects.
2. Keep policy calls inside nodes: use `policy_api.py` as the boundary for
   policy checks and reconciliation.
3. Validate data early: run `TripPlan.model_validate` or the conversion helper
   before calling policy APIs.
4. Store artifacts explicitly: write bytes to disk or object storage in the
   orchestrator, not inside the policy functions.

Tool-like functions intended for LangGraph nodes live in:

- `src/travel_plan_permission/policy_api.py` (policy checks, vendor lookup,
  reconciliation, spreadsheet fill).
- `src/travel_plan_permission/approval_packet.py` (approval emails + PDF bytes).
- `src/travel_plan_permission/prompt_flow.py` (intake question flow, output
  bundle assembly).
- `src/travel_plan_permission/snapshots.py` (validation snapshots + comparisons).
