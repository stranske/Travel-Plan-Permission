<!-- bootstrap for gemini on issue #1751 run:44003950323-1 -->

Serialize exception escalation, tier authorization, and decision under store lock
=================================================================================

- [x] `src/travel_plan_permission/http_service.py:976-1013` — accept `auth_context` in `decide_exception_request` and run `escalate_draft_exceptions(..., persist=False)`, lookup, `ensure_decidable`, `authorize_exception_tier`, decide, audit, and `_persist_state` inside one `@_serialized_store_operation` with rollback on error
- [x] `src/travel_plan_permission/exception_decisions.py:108-156` — delegate `decide_portal_exception` to the single combined store operation
- [x] `tests/python/test_http_service.py` + `tests/python/test_portal_state_store.py` — add deterministic pause-between-read-and-decide concurrency test and two-SQLite-store serialization test
- [x] Named test `tests/python/test_http_service.py::test_exception_decision_reauthorizes_concurrent_escalation` (pauses before commit while concurrent store escalates tier; manager caller cannot approve/reject escalated director/board request) passes: `python3 -m pytest tests/python/test_http_service.py::test_exception_decision_reauthorizes_concurrent_escalation -q`
- [x] Deliberate break → revert, shown in the PR: Remove in-lock escalate + `authorize_exception_tier` check inside `PlannerProposalStore.decide_exception_request` at `http_service.py:990`; manager approves escalated request and test fails; record that the named test fails, then revert and record that it passes.
- [x] The whole test file still passes: `python3 -m pytest tests/python/test_http_service.py -q`

Deliberate break and revert verification
----------------------------------------

1. **Deliberate break**: Removed the in-lock `escalate_draft_exceptions(self, draft_id, persist=False)` and `authorize_exception_tier(...)` calls inside `PlannerProposalStore.decide_exception_request` in `src/travel_plan_permission/http_service.py` and ran:

```text
$ python3 -m pytest tests/python/test_http_service.py::test_exception_decision_reauthorizes_concurrent_escalation -q
tests/python/test_http_service.py FFFF                                   [100%]

FAILED tests/python/test_http_service.py::test_exception_decision_reauthorizes_concurrent_escalation[director-approve] - assert 303 == 403
FAILED tests/python/test_http_service.py::test_exception_decision_reauthorizes_concurrent_escalation[director-reject] - assert 303 == 403
FAILED tests/python/test_http_service.py::test_exception_decision_reauthorizes_concurrent_escalation[board-approve] - assert 303 == 403
FAILED tests/python/test_http_service.py::test_exception_decision_reauthorizes_concurrent_escalation[board-reject] - assert 303 == 403
4 failed, 13 warnings in 2.38s
```

Without the in-lock escalation and tier authorization check, the manager caller succeeded with `303 See Other` instead of being rejected with `403 Forbidden` after the concurrent store escalated the exception request.

2. **Reverted**: Restored the in-lock `escalate_draft_exceptions(self, draft_id, persist=False)` and `authorize_exception_tier(...)` calls in `PlannerProposalStore.decide_exception_request` and re-ran:

```text
$ python3 -m pytest tests/python/test_http_service.py::test_exception_decision_reauthorizes_concurrent_escalation -q
tests/python/test_http_service.py ....                                   [100%]
4 passed, 13 warnings in 2.29s
```

3. **Full test suite verification**:

```text
$ python3 -m pytest tests/python/test_http_service.py -q
227 passed, 14 warnings in 62.38s (0:01:02)

$ python3 -m pytest tests/python/test_portal_state_store.py -q
61 passed, 13 warnings in 2.59s
```
