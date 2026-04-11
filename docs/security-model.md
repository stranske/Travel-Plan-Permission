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

The current planner-facing integration seam uses a bearer-token read contract
for `GET /api/planner/policy-snapshot`.

When `trip-planner` calls TPP over a network boundary, it should send:

- `Authorization: Bearer <TPP_ACCESS_TOKEN>`
- a `trip_id` inside the snapshot request payload
- `known_policy_version` when the planner is revalidating cached guidance

The expected deployment config shape is:

- `TPP_BASE_URL`
- `TPP_ACCESS_TOKEN`
- `TPP_OIDC_PROVIDER`

The snapshot response advertises the currently supported SSO providers
(`azure_ad`, `okta`, `google`) and the required `view` permission so planner
runtime config can be checked against the published seam.

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
