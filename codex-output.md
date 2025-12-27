Added a template-load smoke test so `openpyxl.load_workbook()` explicitly validates the repository template before fill tests run; this directly verifies the acceptance criterion using the same path lookup logic in `src/travel_plan_permission/policy_api.py`. The change is in `tests/python/test_spreadsheet_fill.py`.

Tests run:
- `pytest -q tests/python/test_spreadsheet_fill.py`

Notes:
- Uncommitted change remains in `codex-prompt.md` (not touched by me).

If you want, I can run the full Python test suite as a follow-up.