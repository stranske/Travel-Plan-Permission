Added the missing `department` field to the TripPlan model to align with the orchestration spec, and verified it round‑trips through model serialization via the existing optional‑fields test. Updated the task checklist to reflect the completed spec comparison and field checks in `codex-prompt.md`.

- Added optional `department` to TripPlan in `src/travel_plan_permission/models.py`.
- Extended the optional‑fields test to cover `department` in `tests/python/test_models.py`.
- Marked the relevant tasks complete in `codex-prompt.md`.

Tests run:
- `pytest tests/python/test_models.py`

Next steps:
1) Run the full test suite: `pytest`
2) Run typing checks: `mypy --strict`