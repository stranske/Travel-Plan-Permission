# PR #1003 SQL persistence recovery for audits #1618 / #1622

The original merged PR head is `9bd540e394e90b2ca707f8e2351054081c6ad06b`.
Current-main audit baseline is `853da90a202d3d78ed65610725a78b9c4a5e0d6b`.
The durable provider comparison remains CONCERNS / PASS:
https://github.com/stranske/Travel-Plan-Permission/pull/1003#issuecomment-4349631043

## Reproduced and repaired

At the current-main baseline, four production-facing controls failed:

```
PYTHONPATH=src /opt/anaconda3/bin/python3 -m pytest tests/python/test_portal_state_store.py \
  -k 'snapshot_reads_wait or distinct_review_index or app_lifespan_closes' \
  -q --override-ini addopts=
4 failed, 48 deselected
```

Both SQLite and Postgres readers entered a shared connection while a different
thread held its write transaction. Two independent SQLite stores lost the first
manager-review index entry. FastAPI shutdown left its SQLite connection open.
The same four controls pass after the repair. The Postgres concurrency witness
uses the production store with a mock connection; it is not a live server test.

Connection creation, schema initialization, snapshot reads and close now use the
same reentrant lock as writes. This prevents a Postgres reader's commit from
committing another thread's write. Initialization migrates the legacy review
index singleton transactionally into keyed records without overwriting newer
records. A fifth control deliberately failed before that migration and passes
after it, including deletion/replacement without legacy-key resurrection.
FastAPI lifespan closes the proposal store in a finally block.

## Remaining debt and limits

This repair does not claim multi-instance service coordination. PlannerProposalStore
still saves complete replace=True snapshots and does not reload on cross-instance
cache misses. Distinct standalone SQL record writes are preserved, but stale
service snapshots can delete another writer's records. Existing local-testing
instructions already require a single writer. Production coordination/refresh
and a real Postgres round-trip are the named remaining acceptance sub-scope.
Keep #1618/#1622 open until review dispositions and source acceptance are complete;
link this single existing recovery PR rather than create a duplicate implementation.

No historical deliberate-break output or merge-time check archive is fabricated.
Current historical-head check observations are recorded separately in the closer
receipt; they do not reconstruct what was visible at the historical merge instant.
The current RED/GREEN witnesses above prove the reproduced claims today.

Final focused command (persistence + audit outbox + HTTP routes):
`PYTHONPATH=src /opt/anaconda3/bin/python3 -m pytest tests/python/test_portal_state_store.py tests/python/test_audit.py tests/python/test_http_service.py -q --override-ini addopts=`
passed 318 tests in 24.20s after final connection/close race hardening and migration controls. Ruff passes. Full-repository Black initially exposed eight pre-existing formatting-only files; the exact required formatter repaired them, then the full check passed.
