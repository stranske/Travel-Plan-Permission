#!/usr/bin/env python3
"""Resolve which Python version should run mypy.

This script outputs a single Python version to GITHUB_OUTPUT to ensure mypy
only runs once per CI matrix (avoiding duplicate type-checking across Python
versions).

The script:
1. Reads the target Python version from pyproject.toml's [tool.mypy] section
2. Falls back to the first version in the CI matrix
3. Outputs the resolved version to GITHUB_OUTPUT for workflow use
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def get_mypy_python_version() -> str | None:
    """Extract python_version from pyproject.toml's [tool.mypy] section."""
    pyproject = Path("pyproject.toml")
    if not pyproject.exists():
        return None

    content = pyproject.read_text(encoding="utf-8")

    # Simple parsing - look for python_version in [tool.mypy] section
    in_mypy_section = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("[tool.mypy]"):
            in_mypy_section = True
            continue
        if in_mypy_section:
            if stripped.startswith("["):
                # New section started
                break
            if stripped.startswith("python_version") and "=" in stripped:
                # Extract version value
                value = stripped.split("=", 1)[1].strip().strip('"').strip("'")
                return value
    return None


def main() -> int:
    """Determine and output the Python version for mypy."""
    # Get the current matrix Python version from environment
    matrix_version = os.environ.get("MATRIX_PYTHON_VERSION", "")

    # Get the mypy-configured Python version from pyproject.toml
    mypy_version = get_mypy_python_version()

    # Determine which version to output
    # If mypy has a configured version, use it; otherwise use matrix version
    output_version = mypy_version or (matrix_version or "3.11")

    # Write to GITHUB_OUTPUT
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"python-version={output_version}\n")
        print(f"Resolved mypy Python version: {output_version}")
    else:
        # For local testing
        print(f"python-version={output_version}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
