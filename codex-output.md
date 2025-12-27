Added policy API scenario coverage and reconciled the PR task checklist to reflect the completed work. The new tests exercise mixed blocking/advisory failures and the all‑passing rules path, and the PR body now marks the tasks/acceptance criteria as done after verification in `codex-prompt.md`.

Details:
- Added two new `check_trip_plan` tests to validate fail/pass outcomes and severity mapping in `tests/python/test_policy_api.py`.
- Updated task progress and acceptance checkboxes in `codex-prompt.md` after successful verification.

Tests:
- `python -m pytest tests/python/test_policy_api.py` (markdownlint test skipped because `markdownlint-cli2` is not installed)

Next steps (optional):
1. Run the full suite: `python -m pytest`
2. Install `markdownlint-cli2` if you want the doc lint check to run locally