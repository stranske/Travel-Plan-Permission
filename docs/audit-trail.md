# Audit trail and validation snapshots

The Travel-Plan-Permission service captures two complementary audit streams:

1. **Validation snapshots** — a per-trip, hash-chained record of every
   approval decision (described below).
2. **Durable audit-event log** — a process-spanning, append-only log of
   authentication, RBAC, and proposal-status transitions backed by SQLite.
   See "Durable audit-event log" below.

Validation snapshots provide a deterministic, tamper-evident record of each approval decision so past trips can be re-checked when policies change.

## Snapshot payload

Each snapshot is stored as a compact JSON document (`<trip_id>/<timestamp>.json`):

- `trip_id`: Identifier of the trip the validation was run against.
- `timestamp`: When the snapshot was captured (UTC ISO-8601).
- `policy_version`: Hash of the policy/rule set used for the run.
- `input_data`: Canonicalized trip plan data captured at validation time.
- `results[]`: Array of validation results (rule code, message, severity, blocking).
- `snapshot_hash`: Content hash of the snapshot payload.
- `previous_hash` / `chain_hash`: Hash chain fields that make the store append-only and tamper-evident.

## Capture points

- Snapshots are written whenever an approval decision is recorded (approved, rejected, flagged, or overridden) when a `ValidationSnapshotStore` is provided.
- Captures include the exact validation results used for the decision; if they are missing, the policy validator is run automatically before writing the snapshot.
- The portal admin runtime also records lightweight audit events for draft saves, manager-review submissions, manager decisions, exception requests and decisions, and artifact exports so the current request/review workflow can be inspected end to end from `/portal/admin`.

## Storage and integrity

- Files are written immutably and chained by hash; any modification breaks the chain.
- Snapshots are serialized with compact separators and rejected if they exceed 10KB to keep typical audit entries lightweight.
- The comparison report (`compare_results`) highlights which rules changed between the original snapshot and a re-check under a new policy hash.

## Shipped vs later audit scope

Shipped now:

- request draft + submission transitions
- manager review history
- exception workflow history
- artifact export events from the current portal runtime

Later hardening:

- external append-only audit storage beyond the current runtime process
- reimbursement settlement events from downstream accounting systems
- retention and search controls for enterprise-scale audit archives

## Durable audit-event log

The durable audit-event log lives in
`src/travel_plan_permission/audit.py` and is backed by an append-only
SQLite table named `audit_events`. It complements the in-memory
`security.AuditLog` (used by templates and unit tests) by giving compliance
reviewers and SOX-aligned controls a process-spanning, queryable record of
the four authentication and approval boundaries called out in
`docs/security-model.md`.

### Schema

| Column | Type | Notes |
| ------ | ---- | ----- |
| `id` | TEXT PRIMARY KEY | UUID4 hex assigned at write time. |
| `occurred_at` | TEXT NOT NULL | ISO-8601 UTC timestamp; indexed. |
| `actor_subject` | TEXT NOT NULL | Authenticated subject or service identity. |
| `actor_role` | TEXT | RBAC role at the time of the event (nullable). |
| `event_type` | TEXT NOT NULL | One of the canonical types listed below. |
| `outcome` | TEXT NOT NULL | `success`, `failure`, or a transition state (e.g. `approved`). |
| `target_kind` | TEXT | What the event is about (`planner_route`, `user`, `proposal`, …). |
| `target_id` | TEXT | Stable identifier of the target. |
| `metadata_json` | TEXT NOT NULL | Compact JSON object with event-specific fields. |

### Event-type vocabulary

The shipped vocabulary is intentionally small; new types must be added to
`audit.KNOWN_EVENT_TYPES` and documented here:

- `auth.request` — every call to `authenticate_request` (success and
  every failure branch). Failure rows include a stable
  `metadata.reason_code` (`auth.missing_bearer`, `auth.expired`,
  `auth.invalid_bearer`, `auth.bad_audience`, `auth.bad_provider`,
  `auth.insufficient_permission`, `oidc.<error_code>`).
- `auth.bootstrap_mint` — every call to `mint_bootstrap_token`.
- `rbac.role_change` — successful `requested`, `approved`, and
  `rejected` transitions through
  `SecurityModel.{request,approve,reject}_role_change`; failed
  approval/rejection attempts use `approve` or `reject` plus
  `metadata.reason_code`.
- `rbac.permission_change` — reserved for granular permission edits;
  emitted when explicit permission mutations land.
- `proposal.created` — written by `PlannerProposalStore.record_submission`.
- `proposal.status_change` — written by `record_submission`
  (`submitted`) and by `apply_manager_review_action`
  (`approved` / `rejected` / `needs-info` / `withdrawn`).

### Writing events

Code paths emit events via `audit.write_audit_event(event_type, ...)`. The
helper writes to a module-level default store (`audit.get_default_store()`).
When no durable store is installed, the default is a
`NullAuditEventStore` that silently sinks writes — this matches the
legacy in-memory behavior, so unit tests do not need to opt out.

The HTTP service installs a `SQLiteAuditEventStore` automatically when
`TPP_AUDIT_STATE_PATH` is set in the environment. Operators should set
this alongside `TPP_PORTAL_STATE_PATH` in production runtimes.

### CSV export

Reviewers pull a window without database access via the
`tpp-audit-export` console script:

```bash
TPP_AUDIT_STATE_PATH=/var/lib/tpp/audit-events.sqlite3 \
  tpp-audit-export --since 2026-04-01 --until 2026-05-01 --output report.csv
```

Behavior:

- `--since` is inclusive, `--until` is exclusive.
- `--output -` (the default) writes CSV to stdout.
- `--event-type` filters to a single event type.
- `--store-path PATH` overrides `TPP_AUDIT_STATE_PATH`.
- Exit code `2` is returned when the configured store path does not exist;
  `3` on schema mismatch.

The CSV header matches `audit.CSV_FIELDS` and is stable across releases.

### Retention

The default retention window is **7 years** (2555 days). Override via
`TPP_AUDIT_RETENTION_DAYS`. Pruning is *only* performed by the
documented runbook task:

```bash
TPP_AUDIT_STATE_PATH=/var/lib/tpp/audit-events.sqlite3 \
  tpp-audit-prune
```

Pruning removes rows strictly older than the configured window; rows whose
age equals the window are kept. There is no other delete path.
