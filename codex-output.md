Added a stable policy API module with typed models and wrapper functions, wired the public exports, and covered the new surface with tests so orchestration can import `check_trip_plan`, `list_allowed_vendors`, and `reconcile` directly. This is implemented in `src/travel_plan_permission/policy_api.py` with minimal mapping from `TripPlan` into the existing policy/provider/receipt logic, and the exports are surfaced from `src/travel_plan_permission/__init__.py`.

Tests run:
- `python -m pytest tests/python/test_policy_api.py`
- `python -m mypy src/travel_plan_permission/policy_api.py`

Note: `codex-prompt.md` is untracked and left untouched.

Next steps:
1. Run the full test suite with `python -m pytest` if you want broader verification.