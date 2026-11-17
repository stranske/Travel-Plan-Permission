# Exception decision serialization validation (#1751)

Recent commits were reviewed before continuing: `f514412` contains the serialized
decision implementation, portal delegation, concurrency tests, and deliberate
break/restore evidence; `c293ff2` adds eight rollback regression cases. These
already committed changes satisfy the implementation, delegation, concurrency,
named-test, and deliberate-break tasks. The PR checklist reconciliation was
attempted but rejected by the GitHub write tool's approval policy.

This follow-up adds eight live-namespace regression cases in
`tests/python/test_portal_state_store.py`. These changes remain uncommitted
because this run cannot write `.git` or use GitHub mutation tools.

- [x] Accept authenticated context and perform namespace validation, overdue
  escalation, live tier authorization, decision, audit, and persistence under
  the serialized store operation; restore requests and audits on failure.
- [x] Delegate the portal decision to that combined operation while preserving
  early namespace concealment and rechecking the binding under the lock.
- [x] Add deterministic concurrency tests, two-SQLite-store serialization tests,
  and transaction rollback tests for approval, rejection, and denied authority.
- [x] Verify the named concurrent-escalation regression (four cases).
- [x] Perform the required deliberate break, observe failure, and restore the fix.
- [x] Verify direct store decisions refresh the persisted namespace before escalation.
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

The follow-up verifies that the decision store refreshes the binding written by
a second SQLite store, rather than trusting its cached binding. Both approval
and rejection return 404 when the persisted authentication mode, provider, or
namespace differs. Each denied call makes no snapshot write and leaves requests,
routing, and audits unchanged in memory and on disk. Positive cases confirm that
an entitled director in the same namespace can decide another traveler's overdue
request, with escalation and decision saved in one write.

The named regression and entire state-store file returned **85 passed**,
including all eight new namespace cases and eight previously committed rollback
cases. The rollback tests cover approval and rejection after
an invalid request index, a finalized target, invalid tier entitlements (503),
and a failure after recording the decision audit. Each case verifies that the
entire draft, pre-existing audits, and persisted snapshot remain unchanged, with
no snapshot write attempted. They also verify that overdue sibling escalations
actually happened before the error, so removing escalation cannot make the
rollback assertions pass without exercising rollback.

The entire HTTP test file was rerun and returned **218 passed, 7 failed**. All seven
failures concern existing socket-dependent tests: one JWKS HTTP server and six
Uvicorn process-restart cases. Their socket creation/binding fails with
`PermissionError: [Errno 1] Operation not permitted`. Full-file acceptance remains
unchecked; no tests were skipped or disabled beyond the required `not slow`
marker.

Reproduction commands for this run:

```sh
PYTHONPATH=/tmp/tpp-test-loop:src python3 -m pytest tests/python/test_http_service.py::test_exception_decision_reauthorizes_concurrent_escalation tests/python/test_portal_state_store.py -q -m "not slow"
PYTHONPATH=/tmp/tpp-test-loop:src python3 -m pytest tests/python/test_http_service.py -q -m "not slow"
```

HTTP runs used `PYTHONPATH=/tmp/tpp-test-loop:src` with a temporary
`sitecustomize.py` that bounds selector waits to 10 ms. This accommodates blocked
socketpair sends used for event-loop wakeups; it changes no repository code,
authorization, or test assertions. Every pytest command included `-m "not slow"`.

Black formatted the changed Python test file. The required repository-wide
`black --check --line-length 100 --exclude '(\.workflows-lib|node_modules)' .`
passed for all 242 Python files with `BLACK_NUM_WORKERS=1`. Ruff and
`git diff --check` passed as well.

## Delivery blocker

The follow-up's `git add` failed because `.git/index.lock` cannot be created on
the read-only filesystem. The connected GitHub tools rejected PR checklist
reconciliation, a results/blocker comment, and the `needs-human` label with:
`MCP tool call requires approval, but approval policy is never`. No branch ref was
changed. PR #1754 was verified open and ready for review (`draft=false`).

Commit the new tests and this updated validation record to the existing PR branch
from a writable checkout. Then rerun
`python3 -m pytest tests/python/test_http_service.py -q -m "not slow"` in an
environment that permits socket operations before completing full-file acceptance.
