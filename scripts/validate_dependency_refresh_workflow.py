#!/usr/bin/env python3
"""Validate dependency refresh workflow content against expected uv usage."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

WORKFLOW_PATH = Path(".github/workflows/maint-51-dependency-refresh.yml")
EXPECTED_COMPILE_COMMAND = (
    "uv pip compile --upgrade pyproject.toml --extra dev --extra ocr "
    "--extra orchestration -o requirements.lock"
)
VERIFY_SNIPPET_PATTERN = re.compile(
    r"subprocess\.run\(\s*\[\s*['\"]uv['\"],\s*['\"]pip['\"],\s*['\"]compile['\"],\s*"
    r"['\"]pyproject\.toml['\"],\s*['\"]--extra['\"],\s*['\"]dev['\"],\s*"
    r"['\"]--extra['\"],\s*['\"]ocr['\"],\s*['\"]--extra['\"],\s*['\"]orchestration['\"]",
    re.DOTALL,
)

PIP_COMPILE_PATTERN = re.compile(r"\bpip-compile\b", re.IGNORECASE)
REQUIREMENTS_DEV_PATTERN = re.compile(r"\brequirements-dev\.lock\b", re.IGNORECASE)


def find_workflow_issues(content: str) -> list[str]:
    issues: list[str] = []
    if PIP_COMPILE_PATTERN.search(content):
        issues.append("Found pip-compile usage; expected uv pip compile.")
    if REQUIREMENTS_DEV_PATTERN.search(content):
        issues.append("Found requirements-dev.lock usage; expected single requirements.lock.")
    if EXPECTED_COMPILE_COMMAND not in content:
        issues.append("Expected uv pip compile command with extras is missing.")
    if not VERIFY_SNIPPET_PATTERN.search(content):
        issues.append(
            "Expected verification subprocess.run for uv pip compile with extras is missing."
        )
    return issues


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workflow",
        type=Path,
        default=WORKFLOW_PATH,
        help="Workflow file to validate (default: .github/workflows/maint-51-dependency-refresh.yml).",
    )
    return parser.parse_args(list(argv) if argv else [])


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.workflow.exists():
        print(f"Workflow file not found: {args.workflow}")
        return 2

    content = args.workflow.read_text(encoding="utf-8")
    issues = find_workflow_issues(content)
    if not issues:
        print("Dependency refresh workflow looks aligned with uv pip compile expectations.")
        return 0

    print("Dependency refresh workflow issues detected:")
    for issue in issues:
        print(f"- {issue}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
