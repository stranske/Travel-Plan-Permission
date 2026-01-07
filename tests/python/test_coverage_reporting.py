"""Tests for coverage reporting configuration."""

from __future__ import annotations

import importlib
from pathlib import Path
import sys
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "coverage_report.py"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_script_module():
    """Load the coverage_report script as a module."""
    return importlib.import_module("scripts.coverage_report")


def test_coverage_report_script_exists() -> None:
    """Coverage reporting helper should exist."""
    assert SCRIPT_PATH.exists(), f"Coverage report script not found: {SCRIPT_PATH}"


def test_build_pytest_command_includes_reports() -> None:
    """Pytest command should include coverage report outputs."""
    module = _load_script_module()
    repo_root = Path("/repo")
    absolute_xml = Path("/tmp/coverage.xml")
    cmd = module.build_pytest_command(
        repo_root=repo_root,
        tests_path=Path("tests/python"),
        cov_target="src",
        coverage_xml=absolute_xml,
        coverage_json=Path("coverage.json"),
        pytest_args=["-k", "smoke"],
    )
    assert cmd[0] == sys.executable
    assert f"--cov=src" in cmd
    assert f"--cov-report=xml:{absolute_xml}" in cmd
    assert f"--cov-report=json:{repo_root / 'coverage.json'}" in cmd
    assert cmd[-2:] == ["-k", "smoke"]


def test_build_trend_command_includes_threshold() -> None:
    """Trend command should include minimum coverage threshold and paths."""
    module = _load_script_module()
    repo_root = Path("/repo")
    cmd = module.build_trend_command(
        repo_root=repo_root,
        coverage_xml=Path("coverage.xml"),
        coverage_json=Path("coverage.json"),
        summary_path=Path("coverage-summary.md"),
        artifact_path=Path("coverage-trend.json"),
        minimum=80.0,
        baseline=Path("baseline.json"),
        job_summary=Path("job-summary.md"),
        github_output=Path("github-output.txt"),
        soft=True,
    )
    assert cmd[0] == sys.executable
    assert str(repo_root / "tools" / "coverage_trend.py") in cmd
    assert "--minimum" in cmd
    assert "--baseline" in cmd
    assert "--job-summary" in cmd
    assert "--github-output" in cmd
    assert "--soft" in cmd


def test_main_runs_pytest_and_trend(monkeypatch) -> None:
    """Main should invoke pytest and coverage trend sequentially."""
    module = _load_script_module()
    calls: list[list[str]] = []

    def fake_run(command, cwd=None, check=False):
        calls.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module.main(
        [
            "--tests",
            "tests/python",
            "--coverage-xml",
            "tmp-coverage.xml",
            "--coverage-json",
            "tmp-coverage.json",
            "--summary-path",
            "tmp-summary.md",
            "--artifact-path",
            "tmp-trend.json",
        ]
    )

    assert result == 0
    assert len(calls) == 2


def test_main_returns_pytest_failure(monkeypatch) -> None:
    """Main should return pytest's failure code."""
    module = _load_script_module()
    calls: list[list[str]] = []

    def fake_run(command, cwd=None, check=False):
        calls.append(command)
        return SimpleNamespace(returncode=2)

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module.main(
        [
            "--tests",
            "tests/python",
            "--coverage-xml",
            "tmp-coverage.xml",
            "--coverage-json",
            "tmp-coverage.json",
        ]
    )

    assert result == 2
    assert len(calls) == 1


def test_main_errors_when_trend_missing(monkeypatch) -> None:
    """Main should fail early if the trend script is missing."""
    module = _load_script_module()

    original_exists = module.Path.exists

    def fake_exists(self):
        if self.name == "coverage_trend.py":
            return False
        return original_exists(self)

    monkeypatch.setattr(module.Path, "exists", fake_exists)

    result = module.main(["--tests", "tests/python"])

    assert result == 1
