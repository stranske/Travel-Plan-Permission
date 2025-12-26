Packaged the template and mapping files so `fill-spreadsheet` can find them after a `pip install`, which should satisfy the “CLI works after install” acceptance criteria. This is done via build includes so `config/excel_mappings.yaml` and `templates/travel_request_template.xlsx` end up in site-packages where the existing lookup already searches.

Changes:
- Added hatch build includes for the mapping YAML and template XLSX in `pyproject.toml`.

Files touched:
- `pyproject.toml`

Not run:
- Tests not run (suggest `pytest tests/python/test_cli.py`).

Next steps:
1) `pytest tests/python/test_cli.py`
2) `pip install -e .` and then `fill-spreadsheet --help` / `fill-spreadsheet plan.json output.xlsx` to verify the install path behavior.