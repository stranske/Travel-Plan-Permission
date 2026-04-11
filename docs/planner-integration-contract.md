# Planner Integration Contract

This document defines the planner-facing transport contract between
`trip-planner` and `Travel-Plan-Permission` for the first stable integration
slice owned by issue `#748`.

## Scope

This contract covers:

- the authentication expectation at the planner seam
- the versioning and cache keys that gate planner refresh behavior
- canonical example payloads for policy snapshot, proposal submission,
  proposal status, and evaluation result flows
- the expected call sequence from planner request through policy evaluation

This contract does not replace the canonical planning-side business proposal
contracts in `trip-planner`. It publishes the `Travel-Plan-Permission` side of
that seam with transport-ready examples and validation coverage.

## Authentication

Use a planner-scoped service token for remote transport:

- Header: `Authorization: Bearer <planner-service-token>`
- Contract field: `"auth_scheme": "service_token"`
- Caller identity: `"planner_id": "trip-planner"`

`auth_scheme="none"` remains acceptable only for in-process or same-repo
library usage where no transport boundary exists yet. Once the planner talks to
`Travel-Plan-Permission` over HTTP, treat `service_token` as the required
default.

## Versioning

The planner must treat the following snapshot metadata as cache and
compatibility keys:

- `metadata.policy_version`
- `metadata.approval_rules_version`
- `metadata.provider_registry_version`

Planner behavior:

1. Fetch a fresh policy snapshot before packaging a new proposal.
2. Store the returned version triplet with the proposal submission.
3. Refresh snapshot state immediately when any member of the triplet changes.
4. Treat `metadata.stale_at` as the maximum age for optimistic reuse.
5. If the planner receives an `invalidated` snapshot, stop reusing the cached
   contract and refetch before the next submission.

Breaking-change policy:

- A changed `policy_version` or `approval_rules_version` means policy meaning
  may have shifted and the planner should re-run readiness checks.
- A changed `provider_registry_version` means booking-channel and approved
  provider guidance may have shifted even if the proposal body itself did not.

## Handshake

The expected planner handshake is:

1. `trip-planner` requests a policy snapshot for the destination and travel
   dates.
2. `Travel-Plan-Permission` returns policy rules, booking guidance,
   documentation requirements, approval triggers, and version metadata.
3. `trip-planner` builds a business-mode proposal using that snapshot metadata
   as part of the submission envelope.
4. `Travel-Plan-Permission` accepts the proposal, records the referenced
   snapshot versions, and returns a status resource for later polling.
5. The planner reads the status resource until an evaluation result is attached.
6. The planner consumes the final evaluation result and either proceeds,
   adjusts comparables, or prepares an exception flow.

## Fixture Corpus

Canonical example payloads live in `tests/fixtures/planner/`:

- `policy_snapshot.json`
- `proposal_submission.json`
- `proposal_status.json`
- `evaluation_result.json`

These fixtures are tied together by shared ids and version fields so tests can
detect drift across the end-to-end handshake.

## Notes For `trip-planner`

- Keep proposal export and evaluation result payloads distinct.
- Do not invent planner-only policy meanings that conflict with the snapshot
  metadata returned here.
- Preserve the snapshot version triplet in logs or persisted proposal metadata
  so later verifier work can explain which policy contract was used.
