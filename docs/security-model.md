# Security model

## Roles and permissions

- **traveler** — `view`, `create`
- **approver** — `view`, `approve`
- **finance_admin** — `view`, `approve`, `export`
- **policy_admin** — `view`, `configure`
- **system_admin** — all permissions

Core permissions: `view`, `create`, `approve`, `export`, `configure`.

## Endpoint permission map

| Endpoint | Permission |
| --- | --- |
| `GET /api/itineraries` | `view` |
| `POST /api/itineraries` | `create` |
| `GET /api/itineraries/:id` | `view` |
| `POST /api/approvals/:id/decision` | `approve` |
| `POST /api/approvals/delegate` | `approve` |
| `POST /api/exports/expenses` | `export` |
| `GET /api/exports/audit` | `export` |
| `POST /api/policy/version` | `configure` |
| `POST /api/policy/rules` | `configure` |
| `POST /api/admin/roles` | `configure` |
| `POST /api/admin/sso/validate` | `configure` |

## Planner integration auth contract

The current planner-facing integration seam uses a bearer-token contract for
the planner HTTP surface. The service now requires an explicit auth mode so
startup and readiness can fail deterministically before the service claims it is
ready for planner traffic.

When `trip-planner` calls TPP over a network boundary, it should send:

- `Authorization: Bearer <planner bearer token>`
- a `trip_id` inside the snapshot request payload
- `known_policy_version` when the planner is revalidating cached guidance

The expected deployment config shape is:

- `TPP_BASE_URL`
- `TPP_OIDC_PROVIDER`
- `TPP_AUTH_MODE`
- `TPP_ACCESS_TOKEN` when `TPP_AUTH_MODE=static-token`
- `TPP_BOOTSTRAP_SIGNING_SECRET` when `TPP_AUTH_MODE=bootstrap-token`
- `TPP_BOOTSTRAP_TOKEN_TTL_SECONDS` optionally bounds local or preview bootstrap tokens

### Supported auth modes

- `static-token` keeps the existing fixed bearer-token model and is suitable for
  simple environments where the caller and service share one secret.
- `bootstrap-token` is the preferred local or preview mode. Operators mint a
  short-lived token with `tpp-planner-token`, and the service validates its
  signature, provider, expiry, and required endpoint permission.

The planner-facing endpoints currently require:

- `view` for policy snapshot, execution status, and evaluation-result reads
- `create` for proposal submission

The snapshot response advertises the currently supported SSO providers
(`azure_ad`, `okta`, `google`) and the required `view` permission so planner
runtime config can be checked against the published seam.

For local and preview live tests, `TPP_ACCESS_TOKEN` is a bounded bootstrap
credential, not an auth bypass. Startup fails unless the token is paired with a
subject and one of the modeled roles, and planner-facing routes still
authorize that role against the endpoint permission map before serving the
request.

## Delegation

Approvers can assign a backup approver for `approve` actions. The delegation contract is audit-logged and scoped to approval permissions so a backup can approve on behalf of the primary approver.

## Audit logging

Authentication, authorization, delegation, and role changes are logged with actor, subject, timestamp, outcome, and metadata. Role changes are always recorded as `pending_admin_approval` and later as `approved`/`rejected`.

## Role assignment workflow

Role changes require admin approval (system or policy admins). Requests are tracked with IDs, and approval or rejection is logged for audit trails.

## SSO integration plan

Planned providers with token validation details:

- Azure AD — issuer `https://login.microsoftonline.com/{tenant_id}/v2.0`, JWKS `https://login.microsoftonline.com/common/discovery/v2.0/keys`
- Okta — issuer `https://{yourOktaDomain}/oauth2/default`, JWKS `https://{yourOktaDomain}/oauth2/default/v1/keys`
- Google — issuer `https://accounts.google.com`, JWKS `https://www.googleapis.com/oauth2/v3/certs`

All plans rely on OIDC token validation with PKCE and JWKS verification.

## Security team review

Before rollout, share this model with the security review board for sign-off on role coverage, endpoint mapping, and audit scope.

## Current shipped admin surface

The portal now exposes a practical admin/runtime layer for the current product stage:

- `/portal/admin` shows the active auth mode, the currently selected view-as role (`actor_role`), and the concrete permissions associated with that simulated role selection.
- `/portal/manager/reviews` and `/portal/manager/reviews/{review_id}` expose role-aware review actions. Read-only roles can inspect review state, while approve-capable roles can record review and exception decisions.
- The admin views are intentionally lightweight and in-repo. They are not a full enterprise identity marketplace, SSO admin console, or policy-authoring studio.

## Later hardening work

The following still remain future hardening items rather than shipped-now product surface:

- external identity provider self-service configuration
- durable user/role provisioning outside the in-memory runtime
- richer segregation-of-duties controls and reimbursement-specific finance workflows
