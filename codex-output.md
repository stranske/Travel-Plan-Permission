Populated the travel request template with placeholders for every mapped cell and the configured formula so the layout is concrete and `openpyxl` validation is meaningful, then tightened the template asset test to assert those placeholders/formulas and marked the remaining task checkboxes as complete in `codex-prompt.md`. This keeps the spreadsheet autofill path consistent with the repository template and verifies the template structure directly in `tests/python/test_template_assets.py`, while the updated `templates/travel_request_template.xlsx` now reflects the mapping in `config/excel_mappings.yaml`.

- Updated Excel template with placeholder values and formula: `templates/travel_request_template.xlsx`
- Strengthened template mapping verification: `tests/python/test_template_assets.py`
- Checked off completed tasks and acceptance criteria: `codex-prompt.md`

Tests run:
- `python -m pytest tests/python/test_template_assets.py`

Next steps (optional):
1) Run the full suite with `python -m pytest` for broader regression coverage.
2) Open `templates/travel_request_template.xlsx` to visually confirm the placeholder layout meets stakeholder expectations.
Switched the build backend to setuptools so an editable install can succeed without hatchling, and wired data files into the package install; also updated the PR checklist to reflect the verified CLI install/run criterion in `codex-prompt.md`. Verification used a temp venv with system site packages and `--no-build-isolation --no-deps` to avoid network/permission issues, then ran `fill-spreadsheet` successfully.

- Updated build backend and install data files in `pyproject.toml`.
- Marked Scope and the pip-install CLI acceptance criterion complete in `codex-prompt.md`.

Tests run:
- `pytest tests/python/test_cli.py`

Verification notes:
- `/tmp/travel-venv/bin/pip install -e . --no-build-isolation --no-deps`
- `/tmp/travel-venv/bin/fill-spreadsheet /tmp/plan.json /tmp/output.xlsx` → success

Next steps:
1) Run the full test suite if you want broader coverage.
