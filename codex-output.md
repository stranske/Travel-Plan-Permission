Added a guard so `load_template_mapping` fails fast when the mapping references a missing spreadsheet template, and added a regression test to enforce the template-asset requirement tied to the mapping.

Details:
- `src/travel_plan_permission/mapping.py` now verifies the `metadata.template_file` exists under `templates/` and raises a clear `FileNotFoundError` if not found.
- `tests/python/test_template_assets.py` adds a focused test that rewrites the mapping to reference a missing template and asserts the error.

Tests run:
- `pytest -q tests/python/test_template_assets.py tests/python/test_mapping_integrity.py`

Next steps (optional):
1) Run the full suite: `pytest -q`