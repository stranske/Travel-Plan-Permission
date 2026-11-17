# Exception decision serialization validation (#1751)

Implemented in the workspace on `codex/issue-1751`; delivery is blocked by the
run's write restrictions. No commit or PR update was created.

- [x] Accept authenticated context and perform namespace validation, overdue
  escalation, live tier authorization, decision, audit, and persistence under
  the serialized store operation; restore requests and audits on failure.
- [x] Delegate the portal decision to that combined operation while preserving
  early namespace concealment and rechecking the binding under the lock.
- [x] Add deterministic concurrency tests, two-SQLite-store serialization tests,
  and transaction rollback tests for approval, rejection, and denied authority.
- [x] Verify the named concurrent-escalation regression (four cases).
- [x] Perform the required deliberate break, observe failure, and restore the fix.
- [ ] Verify the entire HTTP test file passes where socket operations are allowed.

## Results

`test_exception_decision_reauthorizes_concurrent_escalation` covers both approve
and reject after a peer escalates a previously read manager request to director
or board. All four cases passed. The peer reads the persisted state afterward
and verifies the request remains escalated with no decision and a denial audit.

Temporarily removing `escalate_draft_exceptions(..., persist=False)` and the
in-lock `authorize_exception_tier` call from `decide_exception_request` produced:

```text
4 failed: assert 303 == 403
```

The full implementation was restored immediately, and the same named test
returned `4 passed`. The deliberately broken implementation was not retained.

The combined HTTP/state-store run returned **283 passed, 7 failed**. All seven
failures concern existing socket-dependent tests: one JWKS HTTP server and six
Uvicorn process-restart cases. Their socket creation/binding fails with
`PermissionError: [Errno 1] Operation not permitted`. All 65 state-store cases
passed, including the five new serialization/rollback cases. All 64 existing
foreign-namespace decision cases passed separately.

HTTP runs used `PYTHONPATH=/tmp/tpp-test-loop:src` with a temporary
`sitecustomize.py` that bounds selector waits to 10 ms. This accommodates blocked
socketpair sends used for event-loop wakeups; it changes no repository code,
authorization, or test assertions. Every pytest command included `-m "not slow"`.

Black formatted the four changed Python files. The required repository-wide
`black --check --line-length 100 --exclude '(\.workflows-lib|node_modules)' .`
passed for all 242 Python files with `BLACK_NUM_WORKERS=1`. Ruff and
`git diff --check` passed as well.

## Delivery blocker

`git add` failed because `.git/index.lock` cannot be created on the read-only
filesystem. The connected GitHub tree-write tool also rejected the operation:
`MCP tool call requires approval, but approval policy is never`. Attempts to
record the results as a PR comment and add `needs-human` were rejected for the
same reason. No branch ref was changed. PR #1754 was verified open and ready for
review (`draft=false`).

Commit the source, tests, and this validation record to the existing PR branch
from a writable checkout. Then rerun
`python3 -m pytest tests/python/test_http_service.py -q -m "not slow"` in an
environment that permits socket operations before completing full-file acceptance.
