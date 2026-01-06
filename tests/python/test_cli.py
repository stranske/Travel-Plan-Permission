from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from travel_plan_permission.cli import main


def test_cli_success_creates_spreadsheet(tmp_path, capsys) -> None:
    input_path = tmp_path / "plan.json"
    output_path = tmp_path / "output.xlsx"
    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "sample_trip_plan_minimal.json"
    input_path.write_text(fixture_path.read_text(encoding="utf-8"), encoding="utf-8")

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


def test_cli_module_help_shows_usage() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    extra_path = str(repo_root / "src")
    if env.get("PYTHONPATH"):
        env["PYTHONPATH"] = f"{extra_path}{os.pathsep}{env['PYTHONPATH']}"
    else:
        env["PYTHONPATH"] = extra_path

    result = subprocess.run(
        [sys.executable, "-m", "travel_plan_permission.cli", "--help"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0
    assert "Generate a completed travel request spreadsheet" in result.stdout
