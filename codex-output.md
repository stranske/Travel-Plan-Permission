Added a pytest check that runs `markdownlint-cli2` against `docs/policy-api.md` when the binary is available, and updated the PR checklist scope item to reflect the completed documentation context. The lint check lives in `tests/python/test_policy_api.py` and resolves to `node_modules/.bin/markdownlint-cli2` first, falling back to a PATH install, then skips cleanly if missing.

Tests: `python -m pytest tests/python/test_policy_api.py` (1 skipped: markdownlint-cli2 not installed)

Notes:
- The markdown lint acceptance item remains unchecked because the lint tool isn’t installed in this environment; the new test will enforce it when `markdownlint-cli2` is available.

Next steps:
1. `npm ci`
2. `npx markdownlint-cli2 docs/policy-api.md`