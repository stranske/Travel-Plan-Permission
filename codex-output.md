Strengthened the public API smoke test to assert the required exports are present in `__all__` and updated the PR task checkboxes to reflect the verified imports and `__version__` access. The new assertions live in `tests/python/test_public_api.py`, and the PR task tracking updates are in `codex-prompt.md`.

Tests run:
- `python -m pytest tests/python/test_public_api.py`

Install verification:
- `pip install -e .` in a clean venv failed because build isolation tried to download `setuptools>=61` and network access is restricted.

Next steps:
1) Re-run `pip install -e .` and `pip install .` in a network-enabled environment (or with a local wheel cache) to complete the remaining install checks.
2) If you want, I can also add a small script to automate the clean-venv install verification once network access is available.