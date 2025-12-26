Refined the policy issue context to carry more structured details while keeping the stable API intact, so orchestration callers can rely on richer context without changing the surface.

Details:
- Expanded `PolicyIssue.context` to accept `dict[str, object]` and now include the rule severity alongside `rule_id` in `src/travel_plan_permission/policy_api.py`.

Tests:
- `python -m mypy src/travel_plan_permission/policy_api.py`
- `python -m pytest tests/python/test_policy_api.py`

Note: Unrelated local changes remain in `codex-prompt.md` and `.workflows-lib/` (not modified by me).

Next steps (pick one):
1. Run the full test suite if you want broader validation.
2. I can continue with the next unchecked task if needed.