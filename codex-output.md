Added the build backend to the sdist payload so source installs have access to `tools/build_backend`, which prevents failures when building from a source distribution. This change is in `tools/build_backend/tp_build_backend.py` to include the backend files (excluding `__pycache__`) when creating the tarball.

Tests and checks run:
- `python -m pytest`
- `. .venv/bin/activate && python -m pip install -e . --no-deps`
- `. .venv/bin/activate && PIP_CACHE_DIR=.pip_cache python -m pip install . --no-deps`

Notes:
- Network is restricted here, so the install checks were run with `--no-deps`.

Next steps:
1) Re-run `pip install -e .` and `pip install .` in an environment with dependency access to fully validate the acceptance criteria.