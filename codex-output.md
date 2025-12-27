Added an explicit check that the required public symbols are present in the package `__all__`, so the root API export contract is now enforced by tests in `tests/python/test_public_api.py`.

Details:
- `tests/python/test_public_api.py` now asserts `__all__` includes `__version__`, `TripPlan`, `check_trip_plan`, `list_allowed_vendors`, `reconcile`, and `fill_travel_spreadsheet`.

Verification:
- `python -m pytest tests/python/test_public_api.py`
- `pip install -e .` in a clean venv failed due to restricted network access when resolving build deps.
- `pip install -e . --no-deps --no-build-isolation` succeeded in a `--system-site-packages` venv.
- `pip install . --no-deps --no-build-isolation` succeeded after setting `PIP_CACHE_DIR=/tmp/pip-cache`.
- Imports verified in the venv: `check_trip_plan`, `list_allowed_vendors`, `reconcile`, `fill_travel_spreadsheet`, `TripPlan`, and `travel_plan_permission.__version__`.

Next steps (pick one):
1) Re-run `pip install -e .` and `pip install .` in a clean venv with network access to fully verify dependency installation.
2) If you want me to, I can add a CI-friendly install smoke test once network access is available.