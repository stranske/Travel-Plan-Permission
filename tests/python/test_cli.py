from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from travel_plan_permission import ExpenseCategory, TripPlan
from travel_plan_permission.cli import main


def _plan() -> TripPlan:
    return TripPlan(
        trip_id="TRIP-CLI-001",
        traveler_name="Taylor Brooks",
        destination="Seattle, WA 98101",
        departure_date=date(2024, 10, 12),
        return_date=date(2024, 10, 15),
        purpose="Partner planning",
        estimated_cost=Decimal("900.00"),
        expense_breakdown={
            ExpenseCategory.CONFERENCE_FEES: Decimal("200.00"),
            ExpenseCategory.AIRFARE: Decimal("500.00"),
        },
    )


def _write_plan(path: Path, plan: TripPlan) -> None:
    payload = plan.model_dump(mode="json")
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_cli_success_creates_spreadsheet(tmp_path, capsys) -> None:
    input_path = tmp_path / "plan.json"
    output_path = tmp_path / "output.xlsx"

    _write_plan(input_path, _plan())

    exit_code = main([str(input_path), str(output_path)])

    assert exit_code == 0
    assert output_path.exists()
    stdout = capsys.readouterr().out
    assert str(output_path) in stdout


def test_cli_invalid_json_returns_error(tmp_path, capsys) -> None:
    input_path = tmp_path / "plan.json"
    output_path = tmp_path / "output.xlsx"
    input_path.write_text("{not-json", encoding="utf-8")

    exit_code = main([str(input_path), str(output_path)])

    assert exit_code == 1
    stderr = capsys.readouterr().err
    assert "Invalid JSON" in stderr


def test_cli_validation_error_returns_error(tmp_path, capsys) -> None:
    input_path = tmp_path / "plan.json"
    output_path = tmp_path / "output.xlsx"
    input_path.write_text(json.dumps({"traveler_name": "Alex"}), encoding="utf-8")

    exit_code = main([str(input_path), str(output_path)])

    assert exit_code == 1
    stderr = capsys.readouterr().err
    assert "TripPlan validation failed" in stderr


def test_cli_missing_input_file_returns_error(tmp_path, capsys) -> None:
    input_path = tmp_path / "missing.json"
    output_path = tmp_path / "output.xlsx"

    exit_code = main([str(input_path), str(output_path)])

    assert exit_code == 1
    stderr = capsys.readouterr().err
    assert "Input file not found" in stderr


def test_cli_help_shows_usage(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])

    assert excinfo.value.code == 0
    stdout = capsys.readouterr().out
    assert "Generate a completed travel request spreadsheet" in stdout
