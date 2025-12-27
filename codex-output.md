Added a dependency-declaration guard test and declared OCR-related optional deps so the import surface is fully represented in `pyproject.toml`, plus updated the task checklist to reflect the completed dependency task.

Details:
- New dependency audit test in `tests/python/test_dependency_declarations.py` to ensure third‑party imports are declared (including optional extras).
- Added optional `ocr` extras with `pillow` and `pytesseract` in `pyproject.toml`.
- Updated task progress/checklist in `codex-prompt.md`.

Tests:
- `python -m pytest tests/python/test_public_api.py tests/python/test_dependency_declarations.py`

Blocked:
- `pip install -e .` in a clean venv failed because build deps could not be fetched without network access.

Next steps:
1) Re-run `pip install -e .` (and then `pip install .`) in a clean venv with network access to satisfy install tasks.
2) After install succeeds, verify imports from `travel_plan_permission` to close the remaining checklist items.