<!-- bootstrap for codex on issue #1748 run:43872024203-1 -->

Exception decision namespace verification
=======================================

- [x] Load the bound draft and reject a foreign auth mode, provider, or identity
  namespace before escalation, exception lookup, tier authorization, or decision.
- [x] Add the named regression test covering approve/reject, foreign provider and
  OIDC issuer/audience/auth-mode bindings, pending/overdue routing, unchanged raw
  and persisted state, SQLite reopen, and same-namespace approver tier checks.
- [x] Verify the regression detects deliberate removal of the guard and passes
  again after restoring it, using the runtime adaptation described below.
- [ ] Confirm the exact named-test and whole-file commands in the ordinary CI
  environment, without the temporary runtime adapter.
- [ ] Commit the implementation on the current PR branch and publish this
  verification evidence in the PR.

Observed results
----------------

With the namespace guard present, the named test passed all 16 parameter cases.
Removing only the new binding/namespace guard from `decide_portal_exception`
caused all 16 cases to fail. In particular, the pending/approve/provider case
reported:

```text
AssertionError: foreign provider: HTTP 303, exception approved
assert 303 == 404
```

That case uses a valid Okta bootstrap bearer with `Permission.APPROVE` against a
Google-bound draft. The overdue cases instead exposed unauthorized escalation
before a tier denial. After restoring the guard, all 16 cases passed again.
The entire receipt test file passed all 62 tests. Repository-wide Black (line
length 100), scoped Ruff, and `git diff --check` also passed.

Commands run for both the deliberate-break and restored named-test checks:

```text
PYTHONPATH=/tmp:src python3 -m pytest -p receipt_test_runtime tests/python/test_portal_receipt_api.py::test_exception_decision_rejects_foreign_namespace -q -m 'not slow'
PYTHONPATH=/tmp:src python3 -m pytest -p receipt_test_runtime tests/python/test_portal_receipt_api.py -q -m 'not slow'
BLACK_NUM_WORKERS=1 black --check --line-length 100 --exclude '(\.workflows-lib|node_modules)' .
ruff check src/travel_plan_permission/exception_decisions.py tests/python/test_portal_receipt_api.py
git diff --check
```

Runtime qualification and handoff
--------------------------------

The sandbox blocks socket writes and local HTTP listeners. The ordinary ASGI
test run hung, and the initial local-JWKS fixture failed with `PermissionError`.
A temporary pytest adapter at `/tmp/receipt_test_runtime.py` selected uvloop for
in-process ASGI requests. For the pre-existing OIDC receipt test, it supplied the
same JWKS document in process instead of through a local HTTP server. No tests
or assertions were skipped; signature, issuer, audience, and permission checks
still ran. The new OIDC fixture itself supplies JWKS in process, consistent with
the existing authentication tests. The adapter is outside the repository and
is not part of the implementation.

An additional exception-focused HTTP service run completed with 55 passes and
six failures, all while starting Unix-socket integration servers prohibited by
the sandbox. These require an environment permitting local listeners.

The commit attempt failed because `.git/index.lock` cannot be created on the
read-only filesystem. Posting the verification comment to PR #1750 and adding
the `needs-human` label were also rejected: the connector requires approval and
this run has approval policy `never`. The implementation and this evidence remain
as working-tree changes.
The PR was confirmed open and ready for review (`draft=false`).

Missing-index verification follow-up (2026-11-16)
----------------------------------------------

Reviewed commits `9b6530e` through `f780337`: implementation, namespace regression,
and deliberate-break evidence are already recorded as complete. No additional
acceptance checkbox can be checked: ordinary-runtime verification remains blocked.

The named regression now covers both existing and missing exception indexes.
Foreign requests must return the same 404 without invoking exception lookup,
escalation, or decision, preserving state before and after SQLite reopen.

With the temporary `/tmp/receipt_event_loop.py` plugin selecting uvloop only,
the named regression passed 64 cases in 31.91 seconds; the whole file passed
110 tests in 54.28 seconds. No tests or assertions were skipped:

```text
PYTHONPATH=/tmp:src python3 -m pytest -p receipt_event_loop tests/python/test_portal_receipt_api.py::test_exception_decision_rejects_foreign_namespace -q -m 'not slow'
PYTHONPATH=/tmp:src python3 -m pytest -p receipt_event_loop tests/python/test_portal_receipt_api.py -q -m 'not slow'
```

The ordinary named and whole-file commands, with `-m 'not slow'`, stalled at the
first ASGI request and were stopped by timeouts. Faulthandler again showed the
default asyncio event loop and cross-thread TestClient call waiting. Black
formatting, the required repository-wide Black check (242 files), scoped Ruff,
and `git diff --check` passed.

Staging failed with `.git/index.lock: Read-only file system`, preventing the
requested commit. PR-body reconciliation, posting the evidence comment, and
adding `needs-human` were rejected with `MCP tool call requires approval, but
approval policy is never`. Changes remain local. PR #1750 is open and ready
for review (`draft=false`).

Follow-up verification
----------------------

The prior implementation is now present in commit `9b6530e`. This follow-up
strengthens the named regression with spies around escalation, exception lookup,
and decision mutation. Every foreign request must return 404 without invoking
any of those methods, both before and after reopening SQLite. The spies wrap
the actual methods, so an authorization regression still exposes real mutation
in the failure message. Same-namespace controls run after the spies are removed.

The ordinary named-test and whole-file commands collected 16 and 62 cases,
respectively, but stalled at the first ASGI request and were interrupted. These
ordinary-runtime acceptance items remain unchecked.

With the same temporary runtime adaptation described above, removing only the
namespace guard again produced 16 failures, including:

```text
test_exception_decision_rejects_foreign_namespace[pending-approve-provider]
AssertionError: foreign provider: HTTP 303, exception approved
assert 303 == 404
```

The guard was restored in a `finally` block and confirmed identical to its
original contents. After strengthening the regression, the named test passed
all 16 cases in 6.28 seconds and the whole file passed all 62 tests in 21.61
seconds. No tests or assertions were skipped. The commands were:

```text
PYTHONPATH=/tmp:src python3 -m pytest -p receipt_test_runtime tests/python/test_portal_receipt_api.py::test_exception_decision_rejects_foreign_namespace -q -m 'not slow'
PYTHONPATH=/tmp:src python3 -m pytest -p receipt_test_runtime tests/python/test_portal_receipt_api.py -q -m 'not slow'
```

Black formatting of the changed Python file, the required repository-wide Black
check (242 files), scoped Ruff, and `git diff --check` passed. No production code
or test-runtime configuration was changed by this follow-up.

The follow-up staging attempt failed with `.git/index.lock: Read-only file
system`, so this follow-up could not be committed. Posting the verification
evidence to PR #1750 and adding the `needs-human` label were rejected with
`MCP tool call requires approval, but approval policy is never`. The PR was
confirmed open and ready for review (`draft=false`). The changes and evidence
remain local; ordinary CI verification, a commit, and publication of the
evidence are still required.

Subject-collision follow-up
--------------------------

- [x] Extend the named regression to foreign bearers that reuse the draft owner's
  subject, as well as bearers with a different subject. All four namespace
  boundaries still cover approve/reject, pending/overdue routing, unchanged state,
  SQLite reopen, and same-namespace tier checks. The foreign OIDC configuration
  grants APPROVE to the colliding subject so the request reaches the guard.

Using the temporary sandbox runtime adapter, the expanded named test passed all
32 cases. Removing only the namespace guard caused all 32 cases to fail in 11.55
seconds. The other-subject/pending/approve/provider case again reported
`foreign provider: HTTP 303, exception approved`. The same-subject equivalent
also exposed the unauthorized approval. The guard was restored byte-for-byte
in a `finally` block. The restored named test passed 32 cases in 13.60 seconds;
the entire file passed 78 tests in 29.73 seconds. No assertions were skipped.
The adapter uses uvloop for ASGI and supplies the existing OIDC receipt test's
JWKS document in process, preserving signature/issuer/audience checks.

```text
PYTHONPATH=/tmp:src python3 -m pytest -p receipt_test_runtime tests/python/test_portal_receipt_api.py::test_exception_decision_rejects_foreign_namespace -q -m 'not slow'
PYTHONPATH=/tmp:src python3 -m pytest -p receipt_test_runtime tests/python/test_portal_receipt_api.py -q -m 'not slow'
```

The ordinary named-test and whole-file commands again stalled at the first ASGI
request and were stopped by timeouts. A run with only the uvloop adaptation
confirmed that the existing JWKS HTTP listener raises `PermissionError: [Errno 1]
Operation not permitted`. The ordinary-runtime acceptance items remain unchecked.
Black formatting, the repository-wide Black check (242 files), scoped Ruff, and
`git diff --check` passed.

Staging this follow-up failed because `.git/index.lock` cannot be created on the
read-only filesystem. Publishing the evidence comment and adding `needs-human`
to PR #1750 were both rejected with `MCP tool call requires approval, but approval
policy is never`. The test changes and this evidence remain uncommitted in the
working tree. Ordinary CI verification, committing, and publishing the evidence
still require a suitably permitted environment.

Offline JWKS verification follow-up
-----------------------------------

The existing receipt OIDC regression now supplies its JWKS document in process,
matching the exception fixture, instead of starting a local HTTP listener. Real
signature, issuer, audience, and namespace validation still run. An additional
assertion checks that a bearer signed with an untrusted key gets 401, and a
fetch spy verifies the configured JWKS URL is fetched once.

With a temporary `/tmp/receipt_event_loop.py` plugin that only selects uvloop
for TestClient, the named regression passed 32 cases in 17.98 seconds and the
whole file passed 78 tests in 32.79 seconds. No authentication or JWKS runtime
patch was needed in that plugin, and no tests or assertions were skipped:

```text
PYTHONPATH=/tmp:src python3 -m pytest -p receipt_event_loop tests/python/test_portal_receipt_api.py::test_exception_decision_rejects_foreign_namespace -q -m 'not slow'
PYTHONPATH=/tmp:src python3 -m pytest -p receipt_event_loop tests/python/test_portal_receipt_api.py -q -m 'not slow'
```

The ordinary named command still stalled at its first ASGI request and was
interrupted. The ordinary whole-file run timed out; faulthandler showed the
default asyncio event loop and the cross-thread TestClient call waiting.
Ordinary-runtime acceptance therefore remains unchecked. Black formatting,
repository-wide Black (242 files), scoped Ruff, and `git diff --check` passed.

Committing was attempted after verification, but staging failed with
`.git/index.lock: Read-only file system`. Posting this evidence and adding
`needs-human` to PR #1750 were rejected with `MCP tool call requires approval,
but approval policy is never`. The verified Python changes remain uncommitted.
The PR was confirmed open and ready for review (`draft=false`).
