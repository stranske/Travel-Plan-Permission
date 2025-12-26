Added a targeted test that monkeypatches the template mapping to confirm `fill_travel_spreadsheet` writes values based on `excel_mappings.yaml`-style cell definitions and still applies date/currency formatting. This directly exercises the mapping behavior without changing the production API in `tests/python/test_spreadsheet_fill.py`.

Tests run:
- `pytest tests/python/test_spreadsheet_fill.py`

Next steps:
1. Run the full test suite if you want broader coverage before final review.