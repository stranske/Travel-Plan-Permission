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

## Planner HTTP Service

Run the planner-facing HTTP adapter locally:

```bash
export TPP_BASE_URL="http://127.0.0.1:8000"
export TPP_OIDC_PROVIDER="google"
export TPP_AUTH_MODE="bootstrap-token"
export TPP_BOOTSTRAP_SIGNING_SECRET="replace-with-a-local-preview-secret"
tpp-planner-service --host 127.0.0.1 --port 8000
```

Use `GET /healthz` for a basic liveness check and `GET /readyz` to verify that
the required planner-facing runtime configuration is present before exercising
the planner routes. The startup command now fails fast unless the planner auth
contract is complete: base URL, supported OIDC provider, and an explicit auth
mode with its matching token configuration must all be present.

For bounded local or preview testing, mint a short-lived planner token with:

```bash
tpp-planner-token --subject trip-planner-local
```

Use the emitted value as `Authorization: Bearer <token>` when calling planner
routes. `TPP_AUTH_MODE="static-token"` plus `TPP_ACCESS_TOKEN` remains
available for simple fixed-token environments.

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
