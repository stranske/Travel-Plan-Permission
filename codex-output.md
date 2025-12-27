Expanded policy API coverage with focused helper tests that exercise resource/template fallbacks, value formatting, nested field resolution, and spreadsheet dropdown/checkbox/formula behavior; this brings policy_api.py coverage above the 80% target. Changes live in `tests/python/test_policy_api_helpers.py`.

Tests run:
- `pytest --cov=travel_plan_permission.policy_api --cov-report=term-missing tests/python/test_policy_api.py tests/python/test_spreadsheet_fill.py tests/python/test_template_assets.py tests/python/test_policy_api_helpers.py`

Notes:
- Working tree still has pre-existing changes in `codex-prompt.md` that I did not touch.

If you want to go further:
1) Run the full test suite with `pytest` to validate everything beyond policy_api coverage.