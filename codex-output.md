Implemented a local PEP 517 build backend so editable and non-editable installs no longer depend on downloading build tools, and wired it into `pyproject.toml`. Added a legacy `setup.cfg`/`setup.py` mirror so source distributions stay usable in tooling that expects setuptools metadata.

Details:
- Custom backend lives in `tools/build_backend/tp_build_backend.py` and builds wheels/editables directly from `pyproject.toml` metadata and `src/` contents.
- `pyproject.toml` now points `build-system` to that backend via `backend-path`, avoiding network calls for build deps.
- Legacy metadata added in `setup.cfg` and `setup.py` for compatibility and sdist completeness.

Verification (network restricted here, so installs were run with `--no-deps`):
- `pip install -e . --no-deps` in a local venv succeeded.
- `pip install . --no-deps` in a local venv succeeded after setting `PIP_CACHE_DIR` to a writable directory.

Files touched:
- `pyproject.toml`
- `tools/build_backend/tp_build_backend.py`
- `setup.cfg`
- `setup.py`

Next steps:
1) If you want to re-verify with dependency resolution, run `pip install -e .` and `pip install .` in an environment with network access.