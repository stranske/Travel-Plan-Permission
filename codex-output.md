Added an advisory-only policy scenario test to confirm `check_trip_plan` stays in a pass state without blocking failures and that the policy version hash follows the engine rules, plus updated the task checklist in `codex-output.md` as a stand‑in PR body update.

- `tests/python/test_policy_api.py`: stubbed engine results to cover advisory-only failures, issue severity mapping, and deterministic policy version hashing.
- `codex-output.md`: added an explicit PR task checklist with the new test work checked off.

Tests run:
- `pytest tests/python/test_policy_api.py` (markdown lint skipped: tool not installed)

Notes:
- I couldn’t find `AGENTS.md` in the repo; I followed `.github/codex/AGENT_INSTRUCTIONS.md` instead.
- `codex-prompt.md` remains modified from before; I left it untouched.

If you want, I can:
1) Run the full test suite.