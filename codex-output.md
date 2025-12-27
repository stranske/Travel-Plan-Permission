Added edge-case coverage around missing cost estimates and empty vendor availability, and expanded vendor destination cases to align with the provider registry behavior. Updates are in `tests/python/test_policy_api.py`.

Tests run:
- `pytest tests/python/test_policy_api.py` (markdownlint check skipped because `markdownlint-cli2` not installed)

Notes:
- Existing unrelated modification remains in `codex-prompt.md` (untouched).

Next steps:
1) If you want, I can mark the relevant task checkboxes as complete and/or run the full test suite.