Added support for selecting the spreadsheet template from mapping metadata so updates to the template file name are honored, and covered it with a focused test to ensure the metadata is passed through. The change is in `src/travel_plan_permission/policy_api.py`, and the new coverage lives in `tests/python/test_spreadsheet_fill.py`.

Tests run:
- `pytest -q tests/python/test_spreadsheet_fill.py`

Notes:
- `codex-prompt.md` is already modified in the working tree and was left untouched.

Next steps (optional):
1) Run the full suite: `pytest -q`