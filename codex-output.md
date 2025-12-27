Spreadsheet fill now has an extra test that asserts currency values are rounded to two decimals, and the PR checklist has been updated to show all tasks/acceptance criteria complete in `codex-prompt.md`.

- Added `test_fill_travel_spreadsheet_rounds_currency_values` in `tests/python/test_spreadsheet_fill.py` to validate rounding and number formats.
- Updated task/acceptance checkboxes and progress in `codex-prompt.md`.

Tests run:
- `pytest tests/python/test_spreadsheet_fill.py`

PR looks ready for review.