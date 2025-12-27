Added a reusable install verification helper so we can consistently validate editable and non‑editable installs in clean venvs, plus safe options for offline environments. The new script lives at `scripts/verify_install.py` and runs both install modes from the repo root.

I ran `python scripts/verify_install.py --no-build-isolation --no-deps --skip-import-check` to confirm the editable and non‑editable build/install steps complete in this sandbox. Full dependency resolution and import verification are still blocked here because the environment has restricted network access, so `pip` cannot download runtime deps.

Tests/verification run:
- `python scripts/verify_install.py --no-build-isolation --no-deps --skip-import-check`

Next steps you can take:
1. Run `python scripts/verify_install.py` in a networked environment to verify full dependency installs and import checks.
2. Alternatively, run `pip install -e .` and `pip install .` in a clean venv to satisfy the remaining acceptance criteria directly.