Updated spreadsheet filling to format any date/datetime values (even outside the explicit date field list) while preserving currency handling, and reconciled the PR task/acceptance checkboxes to reflect the verified work. Changes are in `src/travel_plan_permission/policy_api.py` and `codex-prompt.md`.

Tests run:
- `pytest tests/python/test_spreadsheet_fill.py`

Next steps:
1. Run the full test suite if you want broader validation.