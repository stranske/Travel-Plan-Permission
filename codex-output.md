Bundled the mapping/template assets inside the package and switched loaders to read package resources so installed builds can always find them. Updated packaging metadata and added tests to verify the assets are shipped.

Details
- `src/travel_plan_permission/mapping.py` now falls back to packaged `config/excel_mappings.yaml` and validates template presence against packaged assets.
- `src/travel_plan_permission/policy_api.py` loads the spreadsheet template from package resources via bytes/`BytesIO` for installed builds.
- `pyproject.toml` now ships `config/*.yaml` and `templates/*.xlsx` as package data, with copies added under `src/travel_plan_permission/config` and `src/travel_plan_permission/templates`.
- `tests/python/test_package_data.py` asserts packaged resource presence.

Install verification
- `pip install -e .` succeeded in a fresh venv with `--no-build-isolation` (build isolation tried to fetch setuptools due to restricted network).
- `pip install .` succeeded in the same venv using `PIP_CACHE_DIR=.pip-cache` and `--no-build-isolation` to avoid cache permission issues.
- Imports verified: `travel_plan_permission.__version__`, `check_trip_plan`, `list_allowed_vendors`, `reconcile`, `fill_travel_spreadsheet`, `TripPlan`.

Tests
- `python -m pytest tests/python/test_package_data.py`

Next steps
1. Run the full test suite with `python -m pytest` if you want broader coverage.