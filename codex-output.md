Updated the template mapping metadata to match the repository asset and added a test that loads the template and validates the mapped cell references against a real workbook load to support the spreadsheet autofill requirements. Changes are in `config/excel_mappings.yaml` and `tests/python/test_template_assets.py`.

Tests run:
- `python -m pytest tests/python`

Notes:
- I couldn’t find an `AGENTS.md` under `/home/runner/work/Travel-Plan-Permission/Travel-Plan-Permission`; proceed with best-effort repo instructions.
- I noticed pre-existing uncommitted changes in `.workflows-lib` and `codex-prompt.md`. Let me know how you want to handle those.

Next steps:
1) Confirm whether you want me to include the pre-existing changes in a separate commit or leave them untouched.
2) If you want stronger validation, I can align the Excel template labels with the mapping and assert those labels in tests.