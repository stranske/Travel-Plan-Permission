Added a focused public API import test and declared OCR extras so the package surface is exercised and optional OCR deps are explicitly documented. This keeps the install footprint unchanged while making the root imports and `__version__` assertions explicit.

- Public API test added in `tests/python/test_public_api.py`
- Optional OCR dependencies declared in `pyproject.toml`

Tests run:
- `python -m pytest tests/python/test_public_api.py`

Install verification:
- `pip install -e .` failed in a clean venv because build isolation tried to fetch `setuptools>=61` and network access is restricted.
- `pip install .` failed for the same reason.

Next steps:
1) Re-run `pip install -e .` and `pip install .` in a network-enabled environment (or with a local wheel cache) to satisfy the remaining verification tasks.  
2) If you want lockfiles updated for the new optional extras, regenerate with `pip-compile` and commit the results.