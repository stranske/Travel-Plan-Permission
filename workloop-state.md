## 2026-06-05T22:12Z - opener (codex): issue #1154 export perf lane

- Repo: `stranske/Travel-Plan-Permission`
- Issue: #1154, "Move the 5-second wall-clock export assertion out of the unit-test lane"
- Branch: `codex/issue-1154-export-perf`
- Status: implemented locally; ready to push/open PR after final sync
- Changes:
  - Registered pytest `perf` marker and default-deselected it with `-m "not perf"`.
  - Marked `test_exports_complete_within_five_seconds_for_typical_batch` as `perf`.
  - Added `test_typical_batch_exports_have_expected_outputs` so typical batch functional coverage remains in the default unit lane.
  - Documented opt-in command: `pytest -m perf tests/python/test_export_service.py`.
- Validation:
  - `python -m pytest tests/python/test_export_service.py --collect-only -q` -> 6/7 collected, 1 perf test deselected.
  - `python -m pytest tests/python/test_export_service.py -q` -> 6 passed, 1 deselected.
  - `python -m pytest -m perf tests/python/test_export_service.py -q` -> 1 passed, 6 deselected.
  - Deliberate-break: temporarily removed the default marker filter; `python -m pytest tests/python/test_export_service.py --collect-only -q` collected all 7 tests including `test_exports_complete_within_five_seconds_for_typical_batch`; restored filter and reran collection green.
  - `python -m ruff check pyproject.toml tests/python/test_export_service.py` -> passed.
  - `git diff --check` -> passed.
