Added the orchestration-required TripPlan fields as backward-compatible optionals/defaults, and covered them with a new model test to verify JSON serialization in `src/travel_plan_permission/models.py` and `tests/python/test_models.py`. This keeps existing usage intact while exposing the new API contract fields for downstream orchestration.

Tests run:
- `pytest tests/python/test_models.py`

Next steps:
1. Run `mypy --strict` to confirm type-checking across the full project.
2. Run the full test suite if you want broader coverage beyond the model tests.