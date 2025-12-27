Added a fallback markdown lint check for `docs/policy-api.md` so the test enforces key markdownlint rules even when `markdownlint-cli2` isn’t installed, then verified it with pytest in `tests/python/test_policy_api.py`.

**Details**
- `tests/python/test_policy_api.py`: adds `_basic_markdown_lint` with heading, fence, tab, and newline checks; uses it when `markdownlint-cli2` is missing.

Tests:
- `python -m pytest tests/python/test_policy_api.py -k markdown`

Notes:
- Unrelated local change remains in `codex-prompt.md` (not touched by me).

Next steps:
1. If you want full markdownlint-cli2 coverage, install deps and rerun `npx markdownlint-cli2 docs/policy-api.md`.
2. Run the full test suite if you want broader validation.