# No-terminal demo + internal hosting runbook

This runbook gives a non-developer on a locked-down work PC (no install, no
terminal) a way to exercise the full **traveler → manager → admin** approval
loop in a browser, and gives an operator a deterministic, in-perimeter hosting
option for the real-data zone.

There are two distinct paths, and the split is a privacy requirement, not a
convenience:

| Path | Data | Where it runs | LLM features |
| --- | --- | --- | --- |
| **Synthetic public demo** | Repo fixtures plus synthetic policy-evidence defaults | Public free-tier host (Render) | None |
| **Internal / on-prem** | Real org data | Inside the org perimeter | Disabled |

> **Why two paths?** The org cannot place proprietary travel/expense data on
> community/external SaaS. The public demo is therefore **synthetic only**,
> seeded from repo fixtures plus synthetic policy-evidence defaults, and any
> real-data deployment must stay in-perimeter.

---

## 1. Synthetic public demo (no terminal)

The public service boots with `TPP_DEMO_MODE=1` and seeds its in-memory store
from `tests/fixtures/canonical_trip_plan_realistic.json`,
`tests/fixtures/sample_expense_report_minimal.json`, and synthetic
policy-evidence defaults required to render the manager review. No real data is
present.

### What a reviewer does

1. Open the deployed base URL (see `render.yaml`; this is the synthetic service).
   - **Cold start caveat:** the Render free tier sleeps when idle, so the first
     request can take ~50s while spreadsheet dependencies import before
     `/readyz` is reachable (see `docs/deployment.md`). Wait for readiness
     before treating the demo as down. The scheduled liveness check
     (below) surfaces a genuinely-down demo.
2. Visit `/portal/demo`. This page (only mounted in demo mode) shows a
   short-lived **reviewer bearer token** and a link to the manager review queue.
3. The reviewer/admin surfaces are auth-gated and read the `Authorization`
   header, so attach the token as `Authorization: Bearer <token>` — for example
   with a browser header-injector extension, or from any machine with:

   ```bash
   curl -H "Authorization: Bearer <token>" <base-url>/portal/manager/reviews
   ```

4. Open `/portal/manager/reviews` with the header attached. It renders the
   seeded review queue (a fixture traveler such as **Alex Rivera**). From there
   open a review detail and the admin/exception decision routes to walk the
   complete loop.

Without the header the gate returns **401** — that is expected and proves the
gate still protects the proprietary zone.

### Demo-mode configuration

| Env var | Demo value | Notes |
| --- | --- | --- |
| `TPP_DEMO_MODE` | `1` | Turns on synthetic seeding + `/portal/demo`. Default OFF. |
| `TPP_AUTH_MODE` | `bootstrap-token` | Required so the minted reviewer token validates. |
| `TPP_BOOTSTRAP_SIGNING_SECRET` | operator-provided secret | Signs the reviewer token; must match the GitHub `TPP_DEMO_BOOTSTRAP_SECRET` secret used by the liveness workflow. |
| `TPP_OIDC_PROVIDER` | `google` | Provider label embedded in the token. |
| `TPP_PORTAL_DATABASE_URL` | *(unset)* | If this names a Postgres DSN, demo seeding is **refused** so synthetic data never lands in a real store. |
| `TPP_DEMO_FIXTURE_DIR` | *(unset)* | Optional override for the fixtures directory; defaults to the repo `tests/fixtures`. |

The demo seed and token never touch real data: see
`src/travel_plan_permission/demo_seed.py`.

---

## 2. Internal / on-prem hosting (real-data zone)

For the real-data zone, deploy the same FastAPI + uvicorn service **inside the
org perimeter** so data never leaves it. This app is FastAPI + uvicorn + SQL +
OIDC; it **cannot** run as stlite/Pyodide in the browser, so the in-perimeter
option is a server deployment that is browser-accessible to internal users —
not client-side WebAssembly.

Suitable internal hosts:

- An **internal container host** (e.g. internal Kubernetes/Nomad, or a VM
  running `tpp-planner-service --host 0.0.0.0 --port <port>`).
- **Posit Connect** or an equivalent internal app server.
- An **internal Azure Web App** (or other cloud) deployed into a private VNet
  with no public ingress.

Hard rules for this zone:

- **Data stays in-perimeter.** Point `TPP_PORTAL_STATE_PATH` (or a real
  Postgres via `TPP_PORTAL_DATABASE_URL`) at in-perimeter storage. Do **not**
  set `TPP_DEMO_MODE` here — it is refused when a Postgres backend is
  configured, and must stay off regardless.
- **LLM-dependent features are disabled** in this zone (no real travel/expense
  data is routed to an external LLM). Those agents are a separate effort.
- Authenticate real users with `TPP_AUTH_MODE=oidc` against the org IdP
  (`docs/planner-live-test-runbook.md` covers OIDC config).

---

## 3. Scheduled liveness check

`.github/workflows/maint-render-liveness.yml` runs `tpp-planner-smoke
--base-url <synthetic-demo-url>` on a schedule (and on demand via
`workflow_dispatch`). A down demo produces a **red run** so an outage is
visible rather than silent.

Configure it once:

- Set the repo **variable** `TPP_DEMO_BASE_URL` to the synthetic demo URL (the
  scheduled run skips cleanly until this is set, to avoid spurious red runs).
- Set the repo **secret** `TPP_DEMO_BOOTSTRAP_SECRET` to the same value as the
  service's `TPP_BOOTSTRAP_SIGNING_SECRET`, so the smoke can mint a valid token.

To run it by hand: Actions → **Maint Render Liveness** → *Run workflow*
(optionally pass a `base_url` input). Pass/fail is reported in the Actions log.
