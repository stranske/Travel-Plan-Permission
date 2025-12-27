Updated spreadsheet fill tests to assert the template asset stays unchanged after generating output and close workbooks in `tests/python/test_spreadsheet_fill.py`, plus aligned the task checklist/acceptance criteria in `codex-prompt.md` now that the new behavior is verified.

Tests run:
- `pytest -q tests/python/test_spreadsheet_fill.py`

If you want broader coverage, run the full suite with `pytest`.