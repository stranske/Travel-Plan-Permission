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

### State-retention posture

The hosted Render service is an **intentionally ephemeral synthetic demo**, not a
durable store. Because `TPP_PORTAL_STATE_PATH` points at `/tmp`, submitted drafts
and reviews do not survive a restart/redeploy. To avoid misleading testers, the
portal home renders an in-UI "Ephemeral demo state — submissions are not retained"
banner whenever state is ephemeral (no `TPP_PORTAL_DATABASE_URL` and the state path
lives under a temp directory); the banner disappears automatically once a durable
backend is configured.

Choose one posture explicitly:

- **Ephemeral synthetic demo (default):** keep `TPP_PORTAL_STATE_PATH` on `/tmp`.
  The in-UI banner is the required warning — do not advertise durability for this
  deployment.
- **Durable in-perimeter store:** set `TPP_PORTAL_DATABASE_URL` to an
  org-controlled/managed Postgres (or move `TPP_PORTAL_STATE_PATH` off `/tmp` to a
  persistent disk path) and install the `postgres` extra. Any durable store holding
  real data must stay inside the perimeter — never a community SaaS database.

#### Manual acceptance: portal-state restart verification

When the durable posture is chosen, confirm retention with this checklist
(promoted from the README restart-verification steps):

1. Open the deployed portal and create a draft.
2. Copy the `/portal/review/{draft_id}` URL.
3. Restart/redeploy the service.
4. Reopen the same `/portal/review/{draft_id}` page and confirm the review state,
   submission result, and follow-on review link still render.

If the deployment is intentionally ephemeral, this checklist is expected to fail
after a restart — that is precisely why the in-UI ephemerality banner must be shown.

## Render Backend

`render.yaml` defines a single web service:

- Service: `tpp-planner-api`
- Current staging URL: `https://tpp-planner-api.onrender.com`
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
TPP_BASE_URL=https://tpp-planner-api.onrender.com \
TPP_ACCESS_TOKEN=<token> \
TPP_OIDC_PROVIDER=google \
make full-product-check
```

For a direct TPP smoke check:

```bash
TPP_BASE_URL=https://tpp-planner-api.onrender.com \
TPP_AUTH_MODE=static-token \
TPP_ACCESS_TOKEN=<token> \
TPP_OIDC_PROVIDER=google \
tpp-planner-smoke --base-url "$TPP_BASE_URL"
```
