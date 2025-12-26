Added an explicit `__all__` in `src/travel_plan_permission/policy_api.py` to make the stable API surface explicit, keeping the policy API exports tight and discoverable for orchestration.

Tests run:
- `python -m mypy src/travel_plan_permission/policy_api.py`
- `pytest tests/python/test_policy_api.py`

I noticed `codex-prompt.md` is modified, and I didn’t change it. How would you like to handle that file before I commit?
1) Leave it uncommitted and commit only the policy API change.
2) Include `codex-prompt.md` in the commit (if it’s intended).
