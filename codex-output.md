Added a TripPlan JSON round‑trip test so the new orchestration fields are proven to serialize/deserialize correctly, and updated the PR checklist to reflect the verified scope and acceptance items. The new test in `tests/python/test_models.py` exercises `model_dump_json`/`model_validate_json` for optional fields; the checklist updates live in `codex-prompt.md`.

Tests run:
- `pytest`
- `pytest tests/python/test_models.py`
- `mypy --strict src/ tests/python/` (fails with existing strict‑typing errors in multiple test files, e.g., missing return annotations and dict variance issues in tests)

Next steps:
1) Decide whether to fix the existing mypy strict errors in tests or to adjust the expected mypy invocation for this repo, then rerun `mypy --strict src/ tests/python/`.