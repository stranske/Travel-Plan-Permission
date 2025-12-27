AGENTS.md not found in `/home/runner/work/Travel-Plan-Permission/Travel-Plan-Permission`, so I followed the repo/local instructions.

Added a policy API test that proves passing rules are ignored in issue output, and reconciled the PR checklist after verifying the tests in `tests/python/test_policy_api.py` and `codex-prompt.md`.

- `tests/python/test_policy_api.py`: added a mixed pass/advisory scenario to ensure only failed results surface as issues.
- `codex-prompt.md`: updated task and acceptance checkboxes after the verification run.

Tests:
- `python -m pytest tests/python/test_policy_api.py` (markdown lint test skipped because `markdownlint-cli2` isn’t installed)

Next steps (optional):
1. Run the full suite: `python -m pytest`
2. Install `markdownlint-cli2` if you want the markdown lint test to run locally