Exposed core domain types in the stable policy API so orchestration code can import `TripPlan` and `Receipt` directly from the module without reaching into internal packages. This keeps the public surface in one place and aligns with the plan for a dedicated policy API module in `src/travel_plan_permission/policy_api.py`.

Tests: `pytest tests/python/test_policy_api.py`

Next steps:
1. Run `mypy --strict src/travel_plan_permission/policy_api.py` if you want an explicit type check alongside the test run.
2. Run the full test suite if you need broader validation.