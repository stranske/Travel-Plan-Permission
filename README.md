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

For the full local or preview live-test path, use the
[`Planner Live-Test Runbook`](docs/planner-live-test-runbook.md).

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

The same runtime now also exposes a minimal browser-facing workflow portal:

- Open `http://127.0.0.1:8000/portal` for the portal home.
- Use `http://127.0.0.1:8000/portal/requests/new` to draft and review a travel
  request through the canonical form fields.
- The review screen reuses the repo's canonical conversion, policy snapshot,
  and spreadsheet/export seams before submitting through the existing proposal
  contract.

For bounded local or preview testing, mint a short-lived planner token with:

```bash
tpp-planner-token --subject trip-planner-local
```

Use the emitted value as `Authorization: Bearer <token>` when calling planner
routes. `TPP_AUTH_MODE="static-token"` plus `TPP_ACCESS_TOKEN` remains
available for simple fixed-token environments.

For a live identity-provider boundary, switch the same service to OIDC mode:

```bash
export TPP_AUTH_MODE="oidc"
export TPP_OIDC_PROVIDER="google"
export TPP_OIDC_AUDIENCE="<registered-client-id-or-api-audience>"
export TPP_OIDC_ROLE_MAP='{"sub:user@example.com":"traveler"}'
```

OIDC mode validates the bearer JWT against the provider JWKS, issuer, audience,
expiry, not-before, and subject claims before resolving the subject to a TPP
role. Invalid OIDC bearer tokens are rejected at the HTTP boundary with a
structured `{"detail": {"error_code": "invalid_token", "message": "..."}}`
response body (FastAPI wraps the error fields under `detail`) and a
`WWW-Authenticate: Bearer error="invalid_token"` challenge header. The
role map can also be loaded from `TPP_OIDC_ROLE_MAP_FILE` when the JSON mapping
should live in a mounted config file instead of an environment variable. Set
exactly one of `TPP_OIDC_ROLE_MAP` or `TPP_OIDC_ROLE_MAP_FILE`; `/readyz`
reports `misconfigured` when both are present. Set `TPP_OIDC_SUBJECT_CLAIM` to
use a verified claim other than `sub` as the role-map lookup key. Azure AD and
Okta deployments can override discovery defaults with `TPP_OIDC_ISSUER` and
`TPP_OIDC_JWKS_URL`.

For a browser-facing draft flow on top of the same runtime, open:

```text
http://127.0.0.1:8000/portal
```

The portal stays intentionally small and server-rendered. It lets a traveler
capture draft trip details, see missing canonical inputs before submission,
review policy-lite posture, and download the generated itinerary and summary
artifacts before triggering the existing proposal submission seam.

Portal draft and submission state now persist to a transactional SQL store.
By default the service uses a local SQLite file at
`var/portal-runtime-state.sqlite3` (with WAL journal mode enabled). Override
the path with `TPP_PORTAL_STATE_PATH` for local or preview-safe layouts. For
shared staging deployments, set `TPP_PORTAL_DATABASE_URL` (e.g.
`postgresql://user:pass@host/db`) to switch to the Postgres backend; install
the optional `postgres` extra to pull in the `psycopg` driver. Pre-existing
local state at `var/portal-runtime-state.json` (the deprecated single-file
backend) is imported once on first start when the sibling SQLite file is
created. Pass a `.json`-suffixed path or set `TPP_PORTAL_BACKEND=json` to
keep using the deprecated JSON file during migration. For restart
verification, create a draft, copy the `/portal/review/{draft_id}` URL,
restart the service, and reopen the same page to confirm the review state,
submission result, and follow-on review link still render intentionally
before rechecking artifacts.

Run the repo-native live smoke command against a running service with:

```bash
tpp-planner-smoke
```

The command reuses the repo-owned planner fixtures, verifies that `/readyz`
reports a healthy runtime, confirms the service rejects an unauthenticated
snapshot request, and then exercises the full HTTP handshake over the live
socket: policy snapshot, proposal submission, execution-status readback, and
evaluation-result retrieval.

## Documentation

- [Local Testing Plan](docs/local-testing-plan.md)
- [Planner Live-Test Runbook](docs/planner-live-test-runbook.md)
- [Policy API](docs/policy-api.md)
- [Planner Integration Contract](docs/contracts/planner-integration.md)
- [LangGraph Quickstart](docs/langgraph_quickstart.md)

## Contributing

- Lint Markdown files:

  ```bash
  npx markdownlint-cli2 "**/*.md" "!**/node_modules/**"
  ```

- Run schema validation as shown above.
- Open a pull request with your changes.
