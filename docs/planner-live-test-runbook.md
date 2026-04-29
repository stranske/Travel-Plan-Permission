# Planner Live-Test Runbook

This is the source-of-truth operator runbook for running the planner-facing
Travel Plan Permission service and exercising the live HTTP planner handshake.

Use it when you need to:

- start the planner-facing service locally or against a preview deployment,
- mint or configure a planner bearer token,
- run the blessed smoke path with repo-owned fixtures,
- debug readiness, auth, or contract mismatches without digging through old PRs.

## Prerequisites

Install the package plus development dependencies from the repo root:

```bash
pip install -e ".[dev]"
```

If you prefer `uv`, the equivalent setup is:

```bash
uv sync --extra dev
```

The repo-native entrypoints used below are:

- `tpp-planner-service`
- `tpp-planner-token`
- `tpp-planner-smoke`
- `tpp-cross-repo-smoke`

If they are not on your shell `PATH`, run them via `uv run <command>`.

## Required Runtime Configuration

Set the planner-facing base URL and auth contract before starting the service:

- `TPP_BASE_URL` is required and sets the base URL callers use for the live
  service.
- `TPP_OIDC_PROVIDER` is required and must be `azure_ad`, `okta`, or `google`.
- `TPP_AUTH_MODE` is required and must be `static-token` or
  `bootstrap-token`.
- `TPP_ACCESS_TOKEN` is required only for `static-token` mode and provides the
  fixed bearer token for simple local or preview tests.
- `TPP_BOOTSTRAP_SIGNING_SECRET` is required only for `bootstrap-token` mode
  and provides the shared secret for bounded bootstrap tokens.
- `TPP_BOOTSTRAP_TOKEN_TTL_SECONDS` is optional and defaults to `900` seconds.

## Blessed Local Path

### 1. Export runtime configuration

Bootstrap-token mode is the preferred local path because it exercises the
service-side token validation flow:

```bash
export TPP_BASE_URL="http://127.0.0.1:8000"
export TPP_OIDC_PROVIDER="google"
export TPP_AUTH_MODE="bootstrap-token"
export TPP_BOOTSTRAP_SIGNING_SECRET="replace-with-a-local-preview-secret"
```

If you need the simplest fixed-token path instead:

```bash
export TPP_BASE_URL="http://127.0.0.1:8000"
export TPP_OIDC_PROVIDER="google"
export TPP_AUTH_MODE="static-token"
export TPP_ACCESS_TOKEN="dev-token"
```

### 2. Start the planner-facing service

```bash
tpp-planner-service --host 127.0.0.1 --port 8000
```

Use `--reload` for local development if you want `uvicorn` auto-reload.

### 3. Confirm liveness and readiness

In a second shell:

```bash
curl -s http://127.0.0.1:8000/healthz
curl -s http://127.0.0.1:8000/readyz
```

`/healthz` should return `{"status":"ok"}`. `/readyz` should return HTTP `200`
with `"status":"ready"` before you attempt the planner routes or smoke command.

### 4. Mint a bootstrap token when using bootstrap mode

```bash
tpp-planner-token --subject trip-planner-local
```

The command prints a short-lived bearer token. Use it as:

```bash
Authorization: Bearer <token>
```

You can mint narrower or longer-lived tokens if needed:

```bash
tpp-planner-token --subject trip-planner-local --permission view --permission create --expires-in 1800
```

Skip this step when `TPP_AUTH_MODE=static-token`; the service will accept the
configured `TPP_ACCESS_TOKEN` directly.

### 5. Run the blessed smoke path

```bash
tpp-planner-smoke
```

The smoke command:

- checks `/readyz` before continuing,
- confirms unauthenticated snapshot access returns `401`,
- exercises the policy snapshot flow,
- submits a proposal over HTTP,
- reads execution status back,
- fetches the evaluation result.

By default it uses the packaged planner fixtures shipped with the repo. Override
them only when you need explicit external test data:

```bash
tpp-planner-smoke --fixtures-dir path/to/planner-fixtures
```

The same override also works through `TPP_PLANNER_FIXTURES_DIR`.

### 6. Run the deterministic cross-repo smoke

When a sibling `trip-planner` checkout is available, run the local cross-repo
smoke harness from this repo:

```bash
tpp-cross-repo-smoke --trip-planner-root ../trip-planner
```

The command validates the `trip-planner` TPP contract docs and proposal
fixture, submits the packaged TPP proposal through a local FastAPI test client,
polls proposal status, fetches the evaluation result, then reloads a second TPP
store from the same state file to prove proposal/follow-up state survived
persistence. Set `TRIP_PLANNER_REPO` instead of passing `--trip-planner-root`
when the checkout is not a sibling directory.

## Preview or remote base URLs

For preview or shared environments, point the same commands at the deployed base
URL instead of localhost:

```bash
export TPP_BASE_URL="https://preview.example.net"
```

Then reuse the same `tpp-planner-token` or `TPP_ACCESS_TOKEN` flow and run:

```bash
tpp-planner-smoke --base-url "$TPP_BASE_URL"
```

## Troubleshooting

### `/readyz` returns `503`

The runtime config is incomplete or invalid. Check for:

- missing `TPP_BASE_URL`,
- missing or invalid `TPP_OIDC_PROVIDER`,
- missing `TPP_AUTH_MODE`,
- missing `TPP_ACCESS_TOKEN` for `static-token`,
- missing or too-short `TPP_BOOTSTRAP_SIGNING_SECRET` for `bootstrap-token`.

### `tpp-planner-token` exits with a config error

The token command only works in bootstrap mode. Confirm:

```bash
echo "$TPP_AUTH_MODE"
echo "$TPP_BOOTSTRAP_SIGNING_SECRET"
```

The expected mode is `bootstrap-token`, and the signing secret must be present.

### Smoke fails with `Missing bearer token` or `Invalid bearer token`

The running service and the shell where you minted or supplied the token do not
agree on auth mode or token value. Re-export the auth variables and restart the
service if needed so both shells use the same config.

### Smoke fails because fixtures are unavailable

By default the command reads the packaged planner fixtures. If you passed
`--fixtures-dir` or `TPP_PLANNER_FIXTURES_DIR`, verify that the directory exists
and contains the expected planner integration JSON files.

### Planner routes return `404` for proposal or execution lookups

The service keeps proposal state in memory for bounded local or preview smoke
testing. Re-run the flow from proposal submission rather than calling status or
evaluation endpoints against a fresh process.

### Planner snapshot or evaluation payload looks wrong

Compare the live output to the canonical examples under
`tests/fixtures/planner_integration/` and the contract in
[`docs/contracts/planner-integration.md`](./contracts/planner-integration.md).

## Related References

- [`README.md`](../README.md)
- [`docs/policy-api.md`](./policy-api.md)
- [`docs/contracts/planner-integration.md`](./contracts/planner-integration.md)
