# Travel-Plan-Permission

[![CI](https://github.com/stranske/Travel-Plan-Permission/actions/workflows/ci.yml/badge.svg)](https://github.com/stranske/Travel-Plan-Permission/actions/workflows/ci.yml)

Project to automate and make reproducible the travel plan approval and
reimbursement process.

## Setup

- Install [Node.js](https://nodejs.org/) v20 or later.
- Install the required tools:

  ```bash
  npm install -g markdownlint-cli2 ajv-cli@5 ajv-formats
  ```

## Schema Validation

Compile schemas and validate sample data using [AJV](https://ajv.js.org/):

```bash
ajv compile -s schemas/trip_plan.min.schema.json
ajv compile -s schemas/expense_report.min.schema.json
ajv validate -s schemas/trip_plan.min.schema.json -d tests/fixtures/sample_trip_plan_minimal.json
ajv validate -s schemas/expense_report.min.schema.json -d tests/fixtures/sample_expense_report_minimal.json
```

## Canonical TripPlan Contract

The canonical TripPlan contract is the JSON schema in
`schemas/trip_plan.min.schema.json`. The internal `TripPlan` Python model is
derived from this schema via `canonical_trip_plan_to_model` in
`src/travel_plan_permission/canonical.py`.

## CLI: Fill Travel Spreadsheet

Generate a completed travel request spreadsheet from a TripPlan JSON file:

```bash
fill-spreadsheet path/to/plan.json path/to/output.xlsx
```

To see usage information, run:

```bash
fill-spreadsheet --help
```

## Planner Service Runtime

Start the planner-facing HTTP service locally with:

```bash
tpp-planner-service
```

The service exposes a thin HTTP wrapper around the planner-facing contract
helpers in `travel_plan_permission.policy_api`:

- `GET /healthz`
- `GET /readyz`
- `GET /api/planner/policy-snapshot`
- `POST /api/planner/proposals`
- `GET /api/planner/proposals/{proposal_id}/executions/{execution_id}`
- `GET /api/planner/executions/{execution_id}/evaluation-result`

`/readyz` returns `503` until `TPP_BASE_URL`, `TPP_ACCESS_TOKEN`, and
`TPP_OIDC_PROVIDER` are present in the environment. For local live testing, the
service also boots with a seeded demo trip `TRIP-PLANNER-2001` that matches the
planner integration fixtures under `tests/fixtures/planner_integration/`.

## Documentation

- [Policy API](docs/policy-api.md)
- [LangGraph Quickstart](docs/langgraph_quickstart.md)

## Contributing

- Lint Markdown files:

  ```bash
  npx markdownlint-cli2 "**/*.md" "!**/node_modules/**"
  ```

- Run schema validation as shown above.
- Open a pull request with your changes.
