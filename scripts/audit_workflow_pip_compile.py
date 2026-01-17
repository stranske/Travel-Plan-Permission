#!/usr/bin/env python3
"""Report pip-compile usage in workflow files.

Scope: scan .github/workflows for "pip-compile" strings.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys


WORKFLOWS_DIR = Path(__file__).resolve().parents[1] / ".github" / "workflows"
PATTERN = re.compile(r"\bpip-compile\b", re.IGNORECASE)


def find_occurrences(workflows_dir: Path) -> list[str]:
    matches: list[str] = []
    if not workflows_dir.exists():
        return matches

    for path in sorted(workflows_dir.glob("*.yml")):
        content = path.read_text(encoding="utf-8").splitlines()
        for lineno, line in enumerate(content, start=1):
            if PATTERN.search(line):
                matches.append(f"{path}:{lineno}: {line.strip()}")
    return matches


def main() -> int:
    matches = find_occurrences(WORKFLOWS_DIR)
    if not matches:
        print("No pip-compile usage found in workflows.")
        return 0

    print("pip-compile usage in workflows:")
    for match in matches:
        print(match)
    return 0


if __name__ == "__main__":
    sys.exit(main())
