Exposed the policy API status/severity type aliases from the package root so the orchestration layer can import them directly, and updated the public API test and checklist to match in `src/travel_plan_permission/__init__.py` and `tests/python/test_public_api.py`.

- Updated exports to include `PolicyCheckStatus`, `PolicyIssueSeverity`, and `ReconciliationStatus` in `src/travel_plan_permission/__init__.py`.
- Extended coverage in `tests/python/test_public_api.py`.
- Marked the verified task/criteria in `codex-prompt.md`.

Tests:
- `pytest tests/python/test_public_api.py`

Next steps:
1. Run the full test suite with `pytest` if you want broader validation.