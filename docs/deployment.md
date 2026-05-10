# Hosted Deployment

The lightweight hosted test path is a Render web service running the
planner-facing FastAPI adapter. The default Blueprint uses Render's free web
service so the first Trip Planner + TPP integration test can run without a
committed monthly infrastructure cost.

Free hosting is suitable for functional testing, not durable production use:

- The service can spin down after inactivity. The next request wakes it, which
  can delay the first policy call by 50 seconds or more.
- The default `TPP_PORTAL_STATE_PATH` in `render.yaml` points at `/tmp`, so
  portal and proposal state is disposable across restarts and redeploys.
- Move to a durable database via `TPP_PORTAL_DATABASE_URL` and install the
  `postgres` extra before treating the service as shared staging or production.

## Render Backend

`render.yaml` defines a single web service:

- Service: `tpp-planner-api`
- Runtime: Python
- Plan: free
- Start command: `tpp-planner-service --host 0.0.0.0 --port $PORT`
- Health check: `/healthz`

During the first Render Blueprint setup, provide:

- `TPP_BASE_URL`: the public Render service origin.
- `TPP_ACCESS_TOKEN`: the shared static token that Trip Planner will send.

The Blueprint sets:

- `TPP_AUTH_MODE=static-token`
- `TPP_OIDC_PROVIDER=google`
- `TPP_PORTAL_STATE_PATH=/tmp/tpp/portal-runtime-state.sqlite3`

If Render assigns a random service suffix, update `TPP_BASE_URL` to the final
public URL after creation and redeploy the service.

## Trip Planner Wiring

Set these environment variables on the Trip Planner backend service:

- `TPP_BASE_URL`: the TPP Render service origin.
- `TPP_ACCESS_TOKEN`: the same token configured on TPP.
- `TPP_OIDC_PROVIDER`: `google`.

Then run the Trip Planner full-product verifier with live TPP enabled:

```bash
LIVE_TPP=required \
TPP_BASE_URL=https://<tpp-render-origin> \
TPP_ACCESS_TOKEN=<token> \
TPP_OIDC_PROVIDER=google \
make full-product-check
```

For a direct TPP smoke check:

```bash
TPP_BASE_URL=https://<tpp-render-origin> \
TPP_AUTH_MODE=static-token \
TPP_ACCESS_TOKEN=<token> \
TPP_OIDC_PROVIDER=google \
tpp-planner-smoke --base-url "$TPP_BASE_URL"
```
