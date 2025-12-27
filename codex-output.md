Added a stronger template smoke check by asserting the template file exists and explicitly closing the workbook after loading, reinforcing the `openpyxl.load_workbook()` acceptance criterion in `tests/python/test_spreadsheet_fill.py`. Updated the task checklist in `codex-prompt.md` to reflect the verified acceptance criteria and scope progress now that the template load test passes.

Tests run:
- `pytest -q tests/python/test_spreadsheet_fill.py`

Next steps (optional):
1. Confirm whether the placeholder task/criteria checkboxes should remain open or be removed.
2. Run the full Python test suite if you want broader coverage.