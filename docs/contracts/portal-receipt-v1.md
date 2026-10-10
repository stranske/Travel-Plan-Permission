# Portal receipt v1

This producer contract extends the existing TPP FastAPI app. It does not imply a deployed service or a hosting change. Producer parent: `ac3bfb9f39e7a3144cbe19fd1894d333dfe93b75`; the implementation revision is the containing PR commit. Consumer baseline: existing trip-planner PR1872 at `eed6fcb3127672f79a569f8f2bf3025b6a563333`. The consumer remains unchanged in this producer PR. Its owning closer must pin an accepted producer revision and run the actual two-app contract after integrating this contract; this document is not that end-to-end acceptance.

## Identity and authority

Use the existing `TPP_AUTH_MODE=oidc` identity and validated issuer/audience with configured role permissions. The local preview tests also exercise signed bootstrap tokens minted by the trusted server. The shared `static-token` mode is rejected for these new endpoints: its single service subject cannot establish individual traveler ownership. Never derive an owner from `traveler_name`, a request parameter, a correlation ID, or browser form fields. Bind each receipt to authentication mode, provider, subject and issuer/audience namespace. Wrong owners and absent IDs return the same 404 response. A valid tenant-B token cannot read tenant-A state, even after changing the configured issuer.

The consumer must forward the authenticated traveler's identity through a trusted server-side integration. It must not mint arbitrary subjects from browser input or send a shared service bearer to the browser. This producer does not add token exchange, production identity provisioning, or an anonymous-to-authenticated identity mapping. Bootstrap signing secrets and OIDC/service credentials stay server-side. No token or form payload belongs in query strings, logging or browser storage.

## Create or replay a preparation

`POST /api/planner/portal-handoffs`, with bearer `CREATE` permission:

```json
{
  "handoff_id": "trip-1842-handoff-1",
  "snapshot_version": "trip-revision-7",
  "answers": {"traveler_name": "Synthetic Traveler", "...": "complete portal form fields"}
}
```

`answers` contains the existing portal form's string fields; the abbreviated example is not a complete valid form. Unknown keys and incomplete/invalid required fields return 422. IDs are 1–80 ASCII letters/digits or `_.:-`. Limit: 80 answer fields, 100 characters per key, 4,096 characters per value and 65,536 encoded JSON bytes. Values use the same whitespace/boolean normalization as the real browser form. SHA256 binds the normalized full answer snapshot.

The owner-scoped handoff ID is the retry key. Same version and content return the same persisted draft, fixed preparation timestamp and hash; changed content or version on that key returns 409. For a changed trip, use a new handoff ID and version. A different owner may use the same opaque ID without seeing or replacing the first owner's receipt. Creation and deduplication share the backend's cross-instance operation lock. Bound drafts survive ordinary draft-cache eviction; if all 64 bounded slots are retained, new creation returns 503 without erasing old receipts. Data retention/archival is not implemented by this contract.

The response is a `portal-receipt/v1` object. Preparation creates no manager review, request or decision. The response excludes traveler form details and credentials.

## Browser review and actual submission

1. Call `POST /api/planner/portal-handoffs/{handoff_id}/browser-session?snapshot_version=...` with the owner's bearer `VIEW` permission. It returns `draft_id` and a signed, 15-minute **view-only** `handoff_token`.
2. Render a browser form POST to `/portal/handoff/receipt` with only that token in its body. TPP sets its existing HttpOnly, SameSite handoff cookie and redirects to the saved draft review. The token is absent from the redirect URL. Do not place it in a URL or logs. Expiry/tampering rejects the handoff. The cookie cannot read the receipt API, submit a request, or write a manager decision.
3. The actual existing `/portal/review/{draft_id}/submit` route still requires the owner's authenticated `CREATE` permission. The view-only browser capability does not supply that credential. Deployments must use their established trusted authenticated request path; merely opening the review page is not submission.
4. Existing manager routes remain authoritative for decisions and require `APPROVE` to write. The receipt API contains no manager-decision write operation. Bound draft HTML, artifacts, legacy execution lookups and manager review pages cannot provide alternate cross-owner read paths. Authorized approvers in the same identity namespace retain manager access.

Each bound draft uses a distinct proposal version, preventing different snapshots of the same trip from colliding in the execution store. An unavailable or failed actual submission is rejected before request/review persistence; its receipt remains prepared. Retry of an already submitted immutable snapshot preserves the existing review, including a recorded `changes_requested` decision. To address changes, prepare a new snapshot/key; do not replay an old snapshot to reset a decision.

## Read state and freshness

`GET /api/planner/portal-handoffs/{handoff_id}?snapshot_version=...` requires the owner's bearer `VIEW` permission. The version is mandatory; stale/wrong versions return 409. Reads observe draft and manager state under one backend operation lock. Successful API responses use `Cache-Control: no-store`.

| `state` | Evidence required | Decision fields |
| --- | --- | --- |
| `prepared` | Persisted immutable draft only | null |
| `submitted` | Persisted actual proposal response, manager review not yet present | null |
| `pending_review` | Persisted authoritative pending manager review | null |
| `decision_recorded` | Persisted approved, rejected or changes-requested review | Actual status and timestamp |

Fields: `contract_version`, `handoff_id`, `snapshot_version`, `snapshot_sha256`, `draft_id`, `state`, `prepared_at`, `observed_at`, nullable `request_id`, `execution_id`, `review_id`, `submitted_at`, `decision`, `decision_at`. `observed_at` timestamps this observation; it is not a perpetual freshness guarantee. `submitted_at` comes from the actual manager-review record and can remain null for partial submission evidence. The receipt reports what TPP recorded; it does not independently certify a real person's external-world action.

Absent/foreign receipt: 404, never an inferred success. Stale snapshot: 409. Missing auth: 401; wrong role/provider: 403; OIDC invalid issuer/audience: 401. Existing auth configuration/malformed-bootstrap handling may return 503. A backend/configuration 5xx is **unavailable/unknown**, never absent, submitted or approved. Consumer UI must retain the submitted snapshot/version and show unavailable/stale explicitly rather than reuse a decision for an edited trip. No successful body, request/decision state or credential is fabricated after an error.

## Executable evidence

`python -m pytest tests/python/test_portal_receipt_api.py -q` exercises the actual ASGI app, bearer verification, signed OIDC tokens and local JWKS HTTP server, real SQLite persistence/restart/concurrent clients, browser capability, portal submission and authoritative manager decisions. It tests wrong subjects/issuer/audience, identity-namespace changes, permissions, static-token rejection, duplicate/conflicting snapshots, independent execution IDs, no reset on retry, backend failure and alternate-read denial. No app authentication function is mocked and no production credentials/provider calls are used. This suite validates the producer; consumer integration and its separate interpreter-install CI repair remain on trip-planner1872.
