"""Command-line interface for filling travel request spreadsheets."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from .models import TripPlan
from .policy_api import fill_travel_spreadsheet


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fill-spreadsheet",
        description=(
            "Generate a completed travel request spreadsheet from a TripPlan JSON file."
        ),
    )
    parser.add_argument("input_json", type=Path, help="Path to TripPlan JSON input.")
    parser.add_argument(
        "output_xlsx", type=Path, help="Path to write the completed spreadsheet."
    )
    return parser


def _load_trip_plan(path: Path) -> TripPlan:
    try:
        raw_data = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        msg = f"Input file not found: {path}"
        raise FileNotFoundError(msg) from exc
    except OSError as exc:
        msg = f"Unable to read input file: {path}"
        raise OSError(msg) from exc

    try:
        payload = json.loads(raw_data)
    except json.JSONDecodeError as exc:
        msg = f"Invalid JSON in input file: {path}"
        raise ValueError(msg) from exc

    return TripPlan.model_validate(payload)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        plan = _load_trip_plan(args.input_json)
        output_path = fill_travel_spreadsheet(plan, args.output_xlsx)
    except ValidationError as exc:
        print("Error: TripPlan validation failed.", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Spreadsheet created at {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
