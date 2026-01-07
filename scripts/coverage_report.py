#!/usr/bin/env python3
"""Run pytest with coverage and generate coverage trend artifacts."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _resolve_path(repo_root: Path, path: Path) -> Path:
    """Resolve a path relative to the repository root."""
    if path.is_absolute():
        return path
    return repo_root / path


def build_pytest_command(
    repo_root: Path,
    tests_path: Path,
    cov_target: str,
    coverage_xml: Path,
    coverage_json: Path,
    pytest_args: list[str],
) -> list[str]:
    """Build the pytest command that emits coverage reports."""
    resolved_tests = _resolve_path(repo_root, tests_path)
    resolved_xml = _resolve_path(repo_root, coverage_xml)
    resolved_json = _resolve_path(repo_root, coverage_json)
    command = [
        sys.executable,
        "-m",
        "pytest",
        str(resolved_tests),
        "-m",
        "not slow",
        f"--cov={cov_target}",
        "--cov-report=term-missing",
        f"--cov-report=xml:{resolved_xml}",
        f"--cov-report=json:{resolved_json}",
    ]
    command.extend(pytest_args)
    return command


def build_trend_command(
    repo_root: Path,
    coverage_xml: Path,
    coverage_json: Path,
    summary_path: Path,
    artifact_path: Path,
    minimum: float,
    baseline: Path | None,
    job_summary: Path | None,
    github_output: Path | None,
    soft: bool,
) -> list[str]:
    """Build the coverage trend command."""
    trend_script = repo_root / "tools" / "coverage_trend.py"
    command = [
        sys.executable,
        str(trend_script),
        "--coverage-xml",
        str(_resolve_path(repo_root, coverage_xml)),
        "--coverage-json",
        str(_resolve_path(repo_root, coverage_json)),
        "--summary-path",
        str(_resolve_path(repo_root, summary_path)),
        "--artifact-path",
        str(_resolve_path(repo_root, artifact_path)),
        "--minimum",
        str(minimum),
    ]

    if baseline:
        command.extend(["--baseline", str(_resolve_path(repo_root, baseline))])
    if job_summary:
        command.extend(["--job-summary", str(_resolve_path(repo_root, job_summary))])
    if github_output:
        command.extend(["--github-output", str(_resolve_path(repo_root, github_output))])
    if soft:
        command.append("--soft")

    return command


def main(args: list[str] | None = None) -> int:
    """Run pytest with coverage reporting and generate trend outputs."""
    parser = argparse.ArgumentParser(description="Run coverage reporting and trend summary.")
    parser.add_argument("--tests", type=Path, default=Path("tests/python"))
    parser.add_argument("--cov-target", default="src")
    parser.add_argument("--coverage-xml", type=Path, default=Path("coverage.xml"))
    parser.add_argument("--coverage-json", type=Path, default=Path("coverage.json"))
    parser.add_argument("--summary-path", type=Path, default=Path("coverage-summary.md"))
    parser.add_argument("--artifact-path", type=Path, default=Path("coverage-trend.json"))
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--job-summary", type=Path)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--minimum", type=float, default=80.0)
    parser.add_argument("--soft", action="store_true")
    parsed, pytest_args = parser.parse_known_args(args)

    repo_root = Path(__file__).resolve().parents[1]
    trend_script = repo_root / "tools" / "coverage_trend.py"
    if not trend_script.exists():
        print(f"Coverage trend script not found: {trend_script}", file=sys.stderr)
        return 1

    pytest_command = build_pytest_command(
        repo_root=repo_root,
        tests_path=parsed.tests,
        cov_target=parsed.cov_target,
        coverage_xml=parsed.coverage_xml,
        coverage_json=parsed.coverage_json,
        pytest_args=pytest_args,
    )
    pytest_result = subprocess.run(pytest_command, cwd=repo_root, check=False)
    if pytest_result.returncode != 0:
        return pytest_result.returncode

    trend_command = build_trend_command(
        repo_root=repo_root,
        coverage_xml=parsed.coverage_xml,
        coverage_json=parsed.coverage_json,
        summary_path=parsed.summary_path,
        artifact_path=parsed.artifact_path,
        minimum=parsed.minimum,
        baseline=parsed.baseline,
        job_summary=parsed.job_summary,
        github_output=parsed.github_output,
        soft=parsed.soft,
    )
    trend_result = subprocess.run(trend_command, cwd=repo_root, check=False)
    return trend_result.returncode


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
