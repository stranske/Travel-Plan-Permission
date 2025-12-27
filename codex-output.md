Validated the documentation JSON examples against the live models and recorded the completed PR checklist items after confirming the docs content. Updates are in `tests/python/test_policy_api.py` and `codex-prompt.md`.

- Added a policy API doc-example test to ensure the TripPlan, PolicyCheckResult, and reconciliation JSON payloads validate against current schemas in `tests/python/test_policy_api.py`.
- Updated the PR task and acceptance checkboxes to reflect the completed documentation work in `codex-prompt.md`.

Tests:
- `python -m pytest tests/python/test_policy_api.py`

Notes:
- Markdown lint not run; `node_modules` is missing in this environment.

Next steps:
1. Run `npm ci` then `npx markdownlint-cli2 docs/policy-api.md` to satisfy the lint acceptance criterion.