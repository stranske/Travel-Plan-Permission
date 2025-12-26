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