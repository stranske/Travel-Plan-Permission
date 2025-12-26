Added a subprocess-based CLI help test to validate module invocation and updated the PR checklist to mark verified acceptance criteria.

- New test covers running `python -m travel_plan_permission.cli --help` in `tests/python/test_cli.py`.
- Checked off verified acceptance criteria in `codex-prompt.md`.
- Tests run: `pytest tests/python/test_cli.py`.
- `python -m pip install -e .` failed because build dependency `hatchling` could not be downloaded under restricted network access, so the “pip install then run `fill-spreadsheet`” criterion remains unverified.
- Uncommitted change still present: `.workflows-lib` (pre-existing).

Next steps:
1) Run `python -m pip install -e .` in an environment with access to `hatchling`.
2) Run `fill-spreadsheet plan.json output.xlsx` to confirm the install-path behavior.