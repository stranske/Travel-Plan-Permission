# LangGraph Quickstart

This guide explains how the LangGraph orchestrator should interact with the
TripPlan contract and the policy tooling in this repo.

## Canonical TripPlan contract

The canonical intake contract is the JSON schema in
`schemas/trip_plan.min.schema.json`, represented by `CanonicalTripPlan` in
`src/travel_plan_permission/canonical.py`. The policy APIs
(`check_trip_plan`, `list_allowed_vendors`, `reconcile`,
`fill_travel_spreadsheet`) expect the internal `TripPlan` model in
`src/travel_plan_permission/models.py`, so canonical payloads must be converted
before invoking policy checks.

Example payload (matches the canonical schema):

```json
{
  "type": "trip",
  "traveler_name": "Alex Rivera",
  "business_purpose": "Quarterly planning summit",
  "destination_zip": "60601",
  "city_state": "Chicago, IL",
  "depart_date": "2025-06-10",
  "return_date": "2025-06-12",
  "event_registration_cost": 250.0,
  "hotel": {
    "nightly_rate": 200.0,
    "nights": 3
  },
  "parking_estimate": 45.0
}
```

The canonical schema is a lightweight payload used for early UI or LLM intake.
Convert it into `TripPlan` before calling policy APIs.

## Conversion process (canonical intake -> TripPlan)

Use `load_trip_plan_input` from `src/travel_plan_permission/canonical.py` to
validate the canonical JSON schema and convert it into the internal `TripPlan`.
This loader:

- Builds `destination` from `city_state` + `destination_zip`.
- Maps `business_purpose` to `TripPlan.purpose`.
- Aggregates estimated costs into `expense_breakdown` and `expected_costs`.

Example:

```python
import json
from pathlib import Path

from travel_plan_permission import load_trip_plan_input

payload = json.loads(
    Path("tests/fixtures/sample_trip_plan_minimal.json").read_text(encoding="utf-8")
)

plan_input = load_trip_plan_input(payload)
plan = plan_input.plan
```

Alternatives (advanced/legacy): `canonical_trip_plan_to_model` accepts an
already-validated `CanonicalTripPlan`, while `trip_plan_from_minimal` is a
deprecated wrapper that delegates to `load_trip_plan_input` and applies
overrides like `trip_id` or `origin_city`.

## Run the minimal LangGraph flow locally

The minimal LangGraph orchestration is tracked in
`docs/ORCHESTRATION_PLAN.md` (Phase 2) and implemented as a lightweight graph
in `src/travel_plan_permission/orchestration/graph.py`. You can run the example
entry point locally to validate the flow wiring.

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

3. Run the example module:

   ```bash
   python -m travel_plan_permission.orchestration.example
   ```

   Add `--no-langgraph` if you want to force the fallback graph, pass
   `--output /path/to/travel_request.xlsx` to control the spreadsheet path, and
   use `--minimal-json /path/to/intake.json` if you want to convert a minimal
   payload before running the graph (optionally set `--trip-id` and
   `--origin-city`).

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
