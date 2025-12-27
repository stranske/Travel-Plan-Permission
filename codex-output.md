Expanded the public API export test to cover the policy API models required by the orchestration plan, and updated the PR checklist/progress to reflect the verified work in `codex-prompt.md`.

Details:
- Added assertions for `PolicyIssue`, `PolicyCheckResult`, `ReconciliationResult`, and `Receipt` exports in `tests/python/test_public_api.py`.
- Checked off the new acceptance criteria and task in `codex-prompt.md`.

Tests:
- `pytest tests/python/test_public_api.py`

PR tasks are now complete and ready for review.