Added targeted helper tests to exercise `policy_api` internals (field mapping, context building, policy version hashing, issue formatting, receipt/expense report handling) to push `policy_api.py` coverage above the 80% threshold. Changes are in `tests/python/test_policy_api_helpers.py`.

- `tests/python/test_policy_api_helpers.py` adds helper-focused assertions for mapping, context, policy version hash, issue conversion, and receipt/expense report behavior.
- Coverage for `src/travel_plan_permission/policy_api.py` now reports 91% (per the run below).

Tests run:
- `pytest tests/python/test_policy_api_helpers.py tests/python/test_policy_api.py --cov=travel_plan_permission.policy_api --cov-report=term-missing`

Note: I couldn’t find an `AGENTS.md` in the repo despite the instruction; I proceeded with the existing repo guidance.

If you want, I can:
1) Run the full test suite with coverage.

PR Tasks and Acceptance Criteria
Scope
- [ ] Updated scope for this follow-up.
- [ ] Address unmet acceptance criteria from PR #133.
- [ ] Original scope:
- [ ] The Orchestration Plan (Phase 0) requires tests for key policy scenarios to ensure the API surface is reliable before orchestration integration. Comprehensive tests validate that the policy engine behaves correctly and provides confidence for LangGraph node implementations.

Tasks
- [x] Add policy API coverage for advisory-only outcomes in check_trip_plan.
- [x] Satisfy: Coverage for policy_api.py is >= 80%

Acceptance Criteria
- [ ] Criteria verified as unmet by verifier.
- [x] Coverage for policy_api.py is >= 80%
- [x] Key policy scenario tests cover advisory-only outcomes.
