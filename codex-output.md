Mapped cost center values into the spreadsheet fill pipeline by sourcing them from `TripPlan.department` (fallback to `funding_source`), and added a coverage assertion to confirm the D4 mapping in the filled workbook. This keeps the travel request sheet aligned with the canonical cost center field in the template mapping while staying within the existing fill logic in `src/travel_plan_permission/policy_api.py` and validating it in `tests/python/test_spreadsheet_fill.py`.

Tests run:
- `pytest tests/python/test_spreadsheet_fill.py`

Note: `git status` shows pre-existing modified files `/.workflows-lib` and `codex-prompt.md` that I did not touch—how would you like to handle those?

Next steps (optional):
1. Run the full test suite with `pytest`.
2. I can also add coverage for dropdown/checkbox mappings if desired.