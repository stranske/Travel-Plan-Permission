#!/usr/bin/env python3
"""Report pip-compile and uv pip compile usage in workflow files.

Scope: scan .github/workflows for "pip-compile" and "uv pip compile" strings.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

WORKFLOWS_DIR = Path(__file__).resolve().parents[1] / ".github" / "workflows"
PATTERNS = {
    "pip-compile": re.compile(r"\bpip-compile\b", re.IGNORECASE),
    "uv pip compile": re.compile(r"\buv\s+pip\s+compile\b", re.IGNORECASE),
}
REPLACEMENT_COMMAND = (
    "uv pip compile --upgrade pyproject.toml --extra dev --extra ocr "
    "--extra orchestration -o requirements.lock"
)


def find_occurrences(workflows_dir: Path, pattern: re.Pattern[str]) -> list[str]:
    matches: list[str] = []
    if not workflows_dir.exists():
        return matches

    for path in sorted(workflows_dir.glob("*.yml")):
        content = path.read_text(encoding="utf-8").splitlines()
        for lineno, line in enumerate(content, start=1):
            if pattern.search(line):
                matches.append(f"{path}:{lineno}: {line.strip()}")
    return matches


def render_replacement_suggestions(matches: list[str]) -> list[str]:
    return [f"Replace {match} with: {REPLACEMENT_COMMAND}" for match in matches]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suggest",
        action="store_true",
        help="Include suggested uv pip compile replacements for pip-compile matches.",
    )
    return parser.parse_args(list(argv) if argv else [])


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    all_matches = {
        label: find_occurrences(WORKFLOWS_DIR, pattern) for label, pattern in PATTERNS.items()
    }
    printed = False
    for label, matches in all_matches.items():
        if not matches:
            continue
        printed = True
        print(f"{label} usage in workflows:")
        for match in matches:
            print(match)

    if args.suggest:
        pip_matches = all_matches.get("pip-compile", [])
        if pip_matches:
            printed = True
            print("Suggested replacements:")
            for suggestion in render_replacement_suggestions(pip_matches):
                print(suggestion)

    if not printed:
        print("No pip-compile or uv pip compile usage found in workflows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
