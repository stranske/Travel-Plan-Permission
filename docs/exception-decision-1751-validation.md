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

## Follow-up: concurrent overdue routing

The named concurrency regression now covers both a peer persisting an escalated
tier and a peer persisting an overdue request whose next escalation must happen
inside the deciding store's serialized operation. Each scenario covers director
and board routing, for both approval and rejection: eight cases in total.

This closes a test gap: the original four cases still pass if only the in-lock
escalation call is removed. The new cases require that call as well as live tier
authorization.

- [x] Verify the combined store implementation, including rollback, namespace
  isolation, and two-store serialization: all 86 state-store tests pass.
- [x] Verify the expanded named regression: all eight cases pass.
- [x] Deliberately remove only the in-lock escalation call: the four overdue
  cases fail, while the four already-routed cases pass. Director cases return
  303 instead of 403; board cases retain director routing instead of board.
- [x] Deliberately remove both in-lock escalation and tier authorization: all
  eight cases fail because manager decisions return 303 instead of 403.
- [x] Restore the original production source and rerun: all eight cases pass.
  `git diff --exit-code -- src/travel_plan_permission/http_service.py` confirms
  no retained production mutation.
- [ ] Verify the whole HTTP test file passes in an environment permitting sockets.

These follow-up runs use `PYTHONPATH=/tmp/tpp-1751-loop:src` and `-m "not slow"`.
The normal invocation stalls because this sandbox denies socketpair sends used
to wake the event loop. A temporary `sitecustomize.py`, outside the repository,
bounds selector waits to 10 ms without changing application code or test assertions:

```python
import selectors

_select = selectors.DefaultSelector.select


def _polling_select(self, timeout=None):
    return _select(self, 0.01 if timeout is None else min(timeout, 0.01))


selectors.DefaultSelector.select = _polling_select
```

The required Black check passes for all 242 Python files. Ruff and
`git diff --check` pass as well.

The follow-up whole-file run returned **222 passed, 7 failed** in 99.10 seconds.
The JWKS HTTP-server test fails because TCP socket creation is denied; the six
Uvicorn restart cases fail because Unix-socket binding is denied. Each reports
`PermissionError: [Errno 1] Operation not permitted`. Full-file acceptance
remains unchecked; no failing tests were skipped or disabled.

The commit attempt is still blocked: `git add` cannot create `.git/index.lock`
because `.git` is read-only. The expanded HTTP regression and this follow-up
record remain uncommitted on `codex/issue-1751`.

GitHub rejected the follow-up results comment, verified-task checkbox updates,
and `needs-human` label with `MCP tool call requires approval, but approval
policy is never`. No remote checklist update was applied. PR #1754 was verified
open and ready for review (`draft=false`).

## Follow-up: retry after transaction rollback

Reviewed commits `f514412` through `471fb5c`: the combined store operation,
portal delegation, concurrency tests, and prior deliberate-break evidence are
already present. The first unchecked implementation task is implemented and
verified; its remote checkbox is stale.

Extended `test_exception_decision_persistence_failure_rolls_back_draft` to retry
after restoring audit persistence. Approval, rejection, and denied authority
must each acquire the released operation lock, persist the overdue sibling
routing and exactly one set of audit events, and agree with a reopened store.
The three targeted retry cases pass without the selector workaround.

Verified reconciliation for the PR body:

- [x] Combined serialized store operation with live authorization and rollback.
- [x] Portal delegation with namespace checks.
- [x] Deterministic concurrent escalation and two-store serialization tests.
- [x] Named concurrency regression: eight cases pass.
- [x] Deliberate break and restoration: evidence is recorded in the preceding
  sections from prior iterations; no production mutation remains.
- [ ] Entire HTTP test file passes: still blocked by sandbox socket permissions.

Validation in this follow-up:

```text
python3 -m pytest tests/python/test_portal_state_store.py::test_exception_decision_persistence_failure_rolls_back_draft -q -m "not slow"
3 passed

PYTHONPATH=/tmp/tpp-1751-loop:src timeout 120 python3 -m pytest tests/python/test_http_service.py::test_exception_decision_reauthorizes_concurrent_escalation tests/python/test_portal_state_store.py -q -m "not slow"
94 passed (8 concurrency cases and all 86 state-store cases)

PYTHONPATH=/tmp/tpp-1751-loop:src timeout 180 python3 -m pytest tests/python/test_http_service.py -q -m "not slow"
7 failed, 222 passed in 87.60s
```

The full-file failures remain the JWKS HTTP-server test (TCP socket creation)
and six Uvicorn restart cases (Unix-socket binding), each reporting
`PermissionError: [Errno 1] Operation not permitted`. The unmodified invocations
stall at event-loop wakeups and were interrupted; the successful combined run
and completed full-file run use the temporary selector workaround documented
above. No repository test was skipped or disabled beyond `not slow`.

Black formatting and its required repository-wide check pass (242 files).
Ruff and `git diff --check` pass. `git add` fails because `.git/index.lock`
cannot be created on the read-only filesystem, so this follow-up remains
uncommitted on the existing `codex/issue-1751` branch.

Automatic approval review rejected the PR-body reconciliation and the
`needs-human` label: `MCP tool call requires approval, but approval policy is
never`. The verified checklist above is the local handoff; remote checkboxes
were not changed. Commit these test and validation changes in a writable
checkout, publish the reconciliation, and rerun the full HTTP file where
sockets are permitted before checking off full-file acceptance.

## Follow-up: competing decisions across SQLite stores

Reviewed commits `f514412` through `2b2f70a` before continuing. The first
unchecked implementation task is already implemented and verified; the
remote implementation and named-test checkboxes need reconciliation.

Extended `test_exception_decision_serializes_two_sqlite_stores` with a
competing decision, starting from a cached pending request in each store.
The second store demonstrably contends for the SQLite operation lock while
the first pauses after live tier authorization. After the first commits,
the second refreshes the finalized request and raises
`InvalidExceptionTransition` without writing another snapshot or audit.
Both winning approval and winning rejection are covered.

Verification:

```text
python3 -m pytest tests/python/test_portal_state_store.py::test_exception_decision_serializes_two_sqlite_stores -q -m "not slow"
4 passed

PYTHONPATH=/tmp/tpp-1751-loop:src timeout 120 python3 -m pytest tests/python/test_http_service.py::test_exception_decision_reauthorizes_concurrent_escalation tests/python/test_portal_state_store.py -q -m "not slow"
96 passed (8 named concurrency cases and 88 state-store cases)
```

The combined run uses the temporary selector workaround documented above;
the four targeted SQLite serialization cases pass without it. The plain
named-test invocation timed out at 45 seconds awaiting event-loop wakeups.
No production mutation was needed; previous break/restore evidence remains
applicable. Black formatted the changed test file and its required
repository-wide check passed for all 242 files. Ruff passed as well.

Reconciled checklist based on verified implementation and existing evidence:

- [x] Serialized store operation with live tier authorization and rollback.
- [x] Portal delegation with namespace checks.
- [x] Deterministic concurrency and two-SQLite-store serialization tests.
- [x] Named concurrent-escalation regression: eight cases pass.
- [x] Deliberate break and restoration: recorded in prior sections.
- [ ] Entire HTTP test file passes in an environment permitting sockets.

Automatic approval review rejected the PR-body reconciliation with
`MCP tool call requires approval, but approval policy is never`.
The remote checkboxes remain unchanged.

The full-file run completed:

```text
PYTHONPATH=/tmp/tpp-1751-loop:src timeout 180 python3 -m pytest tests/python/test_http_service.py -q -m "not slow"
7 failed, 222 passed in 98.97s
```

The seven failures are the JWKS HTTP-server case (TCP socket creation) and
six Uvicorn restart cases (Unix-socket binding), each blocked by
`PermissionError: [Errno 1] Operation not permitted`. Full-file acceptance
remains unchecked. No tests were disabled beyond the required marker.

The commit attempt failed at `git add`: `.git/index.lock` cannot be created
on the read-only filesystem. The test changes and this record remain
uncommitted. Automatic approval review also rejected the results comment and
`needs-human` label with the same approval-policy error. Commit the two files
from a writable checkout of the existing PR branch, publish the checklist
reconciliation and evidence, and rerun the full HTTP file where sockets are
permitted before completing acceptance.

## Follow-up: atomic denial snapshots in the named regression

Strengthened `test_exception_decision_reauthorizes_concurrent_escalation` to
observe actual snapshot commits by the deciding store. Each of its eight cases
requires exactly one write containing the final routed tier, no decision,
unchanged prior audits, all peer and in-lock escalation audits, and the denial.
A newly opened store must reproduce that entire snapshot before any listing
can repair missing routing or audit state.

Verified this additional atomicity assertion by temporarily changing the
in-lock escalation from `persist=False` to `persist=True`. All four overdue
cases fail at the new assertion with `assert 2 == 1`; the HTTP denial itself
still succeeds, so the new assertion detects a previously uncovered separate
write. Restored the production source byte-for-byte in a `finally` block.
The earlier required remove-escalation-and-authorization mutation remains
documented above; this follow-up checks the distinct single-commit invariant.

Validation:

```text
PYTHONPATH=/tmp/tpp-1751-loop:src timeout 120 python3 -m pytest tests/python/test_http_service.py::test_exception_decision_reauthorizes_concurrent_escalation tests/python/test_portal_state_store.py -q -m "not slow"
96 passed (8 named cases and 88 state-store cases)

PYTHONPATH=/tmp/tpp-1751-loop:src timeout 90 python3 -m pytest tests/python/test_http_service.py::test_exception_decision_reauthorizes_concurrent_escalation -q -m "not slow"
8 passed after restoring production source
```

The plain named invocation timed out after 40 seconds awaiting event-loop
wakeups. Passing runs use the temporary selector workaround documented above;
no repository event-loop configuration or test assertions were disabled.
Black formatting and its required repository-wide check pass for all 242 files.
Ruff and `git diff --check` pass, and production source has no retained mutation.

- [x] Named concurrent-escalation regression verified with atomic snapshot checks.
- [x] Separate-write mutation fails; restored implementation passes.
- [ ] Whole HTTP file passes with socket operations permitted.

Automatic approval review rejected the PR-body checklist reconciliation with
`MCP tool call requires approval, but approval policy is never`. The named-test
and prior deliberate-break checkboxes could not be reconciled remotely.

The full HTTP run completed with **222 passed, 7 failed** in 91.80 seconds:

```sh
PYTHONPATH=/tmp/tpp-1751-loop:src timeout 180 python3 -m pytest tests/python/test_http_service.py -q -m "not slow"
```

The failures remain the JWKS HTTP-server case and six Uvicorn restart cases;
TCP socket creation or Unix-socket binding raises
`PermissionError: [Errno 1] Operation not permitted`. Full-file acceptance stays
unchecked. No failing tests were skipped or disabled.

The commit attempt failed at `git add` because `.git/index.lock` cannot be
created on the read-only filesystem. The test and validation changes remain
uncommitted on `codex/issue-1751`. Automatic approval review also rejected the
`needs-human` label and results comment with the same approval-policy error. Commit these files
from a writable checkout of the existing PR branch and rerun the full HTTP
file where socket operations are permitted. PR #1754 remains open and ready
for review (`draft=false`).

## Follow-up: authorized decision after concurrent denial

Extended the named concurrency regression to complete the same request after
the stale manager is denied. In all eight cases, a reviewer entitled to the
live director or board tier can approve or reject. The test checks one
additional snapshot, preservation of all escalation and denial audits, the
authenticated deciding actor and approval tier, and agreement with a reopened
SQLite store. This verifies that denial releases coordination and leaves the
request usable by its actual reviewer.

- [x] Expanded named regression: **8 passed**.
- [x] Entire state-store file: **88 passed**.
- [x] Black formatting and repository-wide check: **242 files** pass; Ruff and
  `git diff --check` pass.

The named and state-store runs use the temporary selector workaround documented
above, with `PYTHONPATH=/tmp/tpp-1751-loop:src` and `-m "not slow"`. The plain
named invocation stalled and was interrupted; the plain state-store run also
stalled and was interrupted before the workaround rerun. No repository test
was skipped or disabled beyond `not slow`.

The commit is blocked: `git add -- tests/python/test_http_service.py` cannot
create `.git/index.lock` on the read-only filesystem. The test change remains
uncommitted on the existing PR branch. Automatic approval review rejected the
PR checklist update and `needs-human` label with
`MCP tool call requires approval, but approval policy is never`.

The full HTTP file, also run with that workaround, completed with **222 passed,
7 failed** in 95.00 seconds. The JWKS HTTP-server case and six Uvicorn restart
cases fail because TCP socket creation or Unix-socket binding raises
`PermissionError: [Errno 1] Operation not permitted`.

- [ ] Whole HTTP file passes: rerun where the required socket operations are
  permitted before marking full-file acceptance complete.

The results comment was also rejected by automatic approval review with the
same approval-policy error. PR #1754 was rechecked: open, `draft=false`.
