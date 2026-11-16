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
