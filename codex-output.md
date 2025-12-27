Added explicit PEP 517 requirement/metadata helpers in the custom build backend so pip can query editable/wheel/sdist requirements cleanly, and checked off the install tasks after verifying both install modes. Updated the PR task checkboxes in `codex-prompt.md` to reflect the verified installs.

Details and context:
- `tools/build_backend/tp_build_backend.py` now exposes `get_requires_for_build_*` and `prepare_metadata_for_build_editable`, improving compatibility with pip’s PEP 517 hooks.
- `codex-prompt.md` has the completed task and acceptance checkboxes updated, along with progress.

Tests run:
- `. .venv/bin/activate && PIP_CACHE_DIR=... python -m pip install -e . --no-deps`
- `. .venv/bin/activate && PIP_CACHE_DIR=... python -m pip install . --no-deps`

Notes:
- Network is restricted here, so dependency resolution couldn’t run; installs were verified with `--no-deps` and a writable `PIP_CACHE_DIR`.

Next steps you may want:
1. Run `python -m pip install -e .` in a networked environment to confirm dependency resolution.
2. Run `python -m pip install .` in a networked environment to confirm non-editable install with dependencies.