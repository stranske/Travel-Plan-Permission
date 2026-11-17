# Exception decision serialization validation (#1751)

The serialized decision implementation, portal delegation, and concurrency tests
were already present in `f514412`; `c293ff2` and `3082f91` added rollback and live
namespace regression tests. This follow-up adds five atomicity regression cases
in `tests/python/test_portal_state_store.py`:

- Approval and rejection restore routing and pre-existing audits when recording
  the first overdue escalation raises, before any snapshot write.
- Approval, rejection, and denied authority preserve the committed routing,
  decision, and audits if snapshot reads become unavailable immediately after
  the write. Each case checks that exactly one snapshot was written and that
  in-memory state, the cached snapshot, and a reopened service agree.

## Verified tasks

- [x] Accept authenticated context and perform namespace validation, overdue
  escalation, live tier authorization, decision, audit, and persistence under
  the serialized store operation; restore requests and audits on failure.
- [x] Delegate the portal decision to that combined operation while preserving
  early namespace concealment and rechecking the binding under the lock.
- [x] Add deterministic concurrency tests, two-SQLite-store serialization tests,
  and transaction rollback tests for approval, rejection, and denied authority.
- [x] Verify the named concurrent-escalation regression (four cases).
- [x] Perform the deliberate break, observe failure, restore, and verify passing.
- [x] Verify direct store decisions refresh the persisted namespace before escalation.
- [ ] Verify the entire HTTP test file passes where socket operations are allowed.

## Current run: 2026-11-17

The named regression pauses at the former read/write gap while a second SQLite
store escalates the request to director or board. Both approval and rejection by
a manager return 403, preserve the escalated request without a decision, and
persist one denial audit identifying the live required tier.

The required deliberate break was repeated in this run. Temporarily removing
`escalate_draft_exceptions(..., persist=False)` and replacing the in-lock
`authorize_exception_tier` call with the target's routed approval level produced:

```text
FAILED test_exception_decision_reauthorizes_concurrent_escalation[director-approve]
FAILED test_exception_decision_reauthorizes_concurrent_escalation[director-reject]
FAILED test_exception_decision_reauthorizes_concurrent_escalation[board-approve]
FAILED test_exception_decision_reauthorizes_concurrent_escalation[board-reject]
4 failed: assert 303 == 403
```

The original implementation was restored in a `finally` block. The combined
rerun of the named regression and entire state-store file returned **90 passed**
(four named cases and 86 state-store cases, including the five new regressions).
The production source has no retained mutation.

Reproduction commands:

```sh
PYTHONPATH=/tmp/tpp-test-loop:src python3 -m pytest tests/python/test_http_service.py::test_exception_decision_reauthorizes_concurrent_escalation tests/python/test_portal_state_store.py -q -m "not slow"
PYTHONPATH=/tmp/tpp-test-loop:src python3 -m pytest tests/python/test_http_service.py -q -m "not slow"
```

The unmodified test invocation stalls because this environment denies socketpair
sends used for event-loop wakeups. The runs above use a temporary
`/tmp/tpp-test-loop/sitecustomize.py` that bounds selector waits to 10 ms. This
changes no repository code, authorization, or test assertions. The environment
also denies TCP socket creation. Every pytest run includes `-m "not slow"`.

The whole HTTP file returned **218 passed, 7 failed** in 84.71 seconds. The
failures are the existing JWKS HTTP-server case and six Uvicorn process-restart
cases: socket creation or Unix-domain socket binding raises
`PermissionError: [Errno 1] Operation not permitted`. No tests were skipped or
disabled beyond the required `not slow` marker. Full-file acceptance remains
unchecked until it can be rerun where those socket operations are permitted.

Black formatted the changed test file, and the required repository-wide check
passed for all 242 Python files:

```sh
black --line-length 100 tests/python/test_portal_state_store.py
BLACK_NUM_WORKERS=1 black --check --line-length 100 --exclude '(\.workflows-lib|node_modules)' .
```

Ruff and `git diff --check` also passed.

## Delivery blocker

The commit attempt failed at `git add` because `.git/index.lock` cannot be
created on the read-only filesystem. The five new regression cases and this
validation record remain uncommitted on the existing `codex/issue-1751` branch.
No production code mutation remains, and no new branch or pull request was created.

The GitHub tool rejected both the results comment and the `needs-human` label
with `MCP tool call requires approval, but approval policy is never`. Consequently
this run could not publish the break/restore evidence or reconcile the PR's
unchecked tasks. PR #1754 was verified open with `draft=false`.

Commit `tests/python/test_portal_state_store.py` and this record from a writable
checkout of the existing PR branch. Publish the validation evidence and rerun
`python3 -m pytest tests/python/test_http_service.py -q -m "not slow"` where socket
operations are permitted before marking full-file acceptance complete.
