Added a CLI entry point that parses input/output paths, validates TripPlan JSON, fills the spreadsheet, and returns clear success/error messaging. Wired the console script in `pyproject.toml` and documented usage in `README.md` so users can discover `fill-spreadsheet` quickly.

- `src/travel_plan_permission/cli.py` implements argparse, JSON loading/validation, and friendly error handling around `fill_travel_spreadsheet`.
- `pyproject.toml` exposes `fill-spreadsheet` as a console script.
- `README.md` includes a short CLI usage section.

Tests/verification:
- `python -m travel_plan_permission.cli tmp_trip_plan.json tmp_trip_plan_output.xlsx`
- `python -m travel_plan_permission.cli tmp_trip_plan_invalid.json tmp_invalid_output.xlsx`
- `python -m travel_plan_permission.cli tmp_trip_plan_missing.json tmp_missing_output.xlsx`

Notes:
- Commit created: “Add CLI for travel spreadsheet generation”.

Next steps (pick one):
1. Run `pytest` to exercise the existing spreadsheet/template tests.
2. Try `pip install -e .` and run `fill-spreadsheet --help` to validate the entry point in an installed context.