#!/usr/bin/env python3
"""Report pip-compile and uv pip compile usage in workflow files.

Scope: scan .github/workflows for "pip-compile" and "uv pip compile" strings.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

WORKFLOWS_DIR = Path(__file__).resolve().parents[1] / ".github" / "workflows"
PATTERNS = {
    "pip-compile": re.compile(r"\bpip-compile\b", re.IGNORECASE),
    "uv pip compile": re.compile(r"\buv\s+pip\s+compile\b", re.IGNORECASE),
}


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


def main() -> int:
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

    if not printed:
        print("No pip-compile or uv pip compile usage found in workflows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
