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

## CLI: Fill Travel Spreadsheet

Generate a completed travel request spreadsheet from a TripPlan JSON file:

```bash
fill-spreadsheet path/to/plan.json path/to/output.xlsx
```

To see usage information, run:

```bash
fill-spreadsheet --help
```

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
