Added explicit planned/actual/variance assertions for reconciliation results so expense variance behavior is verified, and updated the PR task checklist after the test run in `tests/python/test_policy_api.py` and `codex-prompt.md`.

Tests run:
- `pytest tests/python/test_policy_api.py` (markdownlint-cli2 skipped: not installed)

PR tasks now look complete and the PR appears ready for review. If you want a final verification pass, you could:
1) Run the full test suite.
