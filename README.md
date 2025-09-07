# Travel-Plan-Permission

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
ajv compile -s schemas/trip_plan.min.schema.json \
  --spec=draft2020 -c ajv-formats
ajv compile -s schemas/expense_report.min.schema.json \
  --spec=draft2020 -c ajv-formats
ajv validate -s schemas/trip_plan.min.schema.json \
  -d tests/fixtures/sample_trip_plan_minimal.json \
  --spec=draft2020 -c ajv-formats
ajv validate -s schemas/expense_report.min.schema.json \
  -d tests/fixtures/sample_expense_report_minimal.json \
  --spec=draft2020 -c ajv-formats
```

## Contributing

- Lint Markdown files:

  ```bash
  npx markdownlint-cli2 "**/*.md" "!**/node_modules/**"
  ```

- Run schema validation as shown above.
- Open a pull request with your changes.
