Added a CLI error-handling test for missing input files and explicitly called out `fill-spreadsheet` as the Phase 1 early deliverable in the orchestration plan to align scope with the acceptance criteria. The new test covers the user-friendly error path that the CLI already implements, while the doc update makes the Phase 1 CLI deliverable unmistakable in `docs/ORCHESTRATION_PLAN.md`.

- Updated documentation in `docs/ORCHESTRATION_PLAN.md` to explicitly name the `fill-spreadsheet` CLI as the Phase 1 early deliverable.
- Added a missing-input-file CLI test in `tests/python/test_cli.py` to validate non-zero exit and a clear error message.

Tests:
- `pytest tests/python/test_cli.py`

Next steps (optional):
1. Run the full test suite with `pytest`.
2. Try an end-to-end CLI run via `fill-spreadsheet plan.json output.xlsx` in a local install if you want to validate the console script wiring.