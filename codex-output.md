Added a spreadsheet autofill API that maps TripPlan data into the Excel template with date/currency formatting, plus a template file and unit test coverage. The new workflow lives in `src/travel_plan_permission/policy_api.py` and uses `config/excel_mappings.yaml` to drive cell placement, while `templates/travel_request_template.xlsx` provides the required template and `tests/python/test_spreadsheet_fill.py` validates mapping/formatting behavior. `src/travel_plan_permission/__init__.py` now exports the new function.

- New API: `src/travel_plan_permission/policy_api.py`
- Template: `templates/travel_request_template.xlsx`
- Tests: `tests/python/test_spreadsheet_fill.py`
- Export: `src/travel_plan_permission/__init__.py`

Tests run:
- `python -m pytest tests/python/test_spreadsheet_fill.py`

Notes:
- `codex-prompt.md` is still modified in the worktree (pre-existing).

Next steps:
1. Run the full test suite if you want broader coverage.