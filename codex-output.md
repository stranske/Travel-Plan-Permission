Adjusted the policy API’s issue context typing to use JSON-safe primitive values, keeping the stable surface explicit in `src/travel_plan_permission/policy_api.py`. Updated the PR task checklist after verification in `codex-prompt.md`.

Tests run:
- `mypy src/travel_plan_permission/policy_api.py`
- `python -m pytest`

PR tasks are now complete and the branch is ready for review.