#!/usr/bin/env python3
"""Keep pyproject.toml tool pins aligned with the automation pin file.

This script ensures that the tool versions specified in pyproject.toml match
the versions pinned in .github/workflows/autofix-versions.env. This alignment
prevents "works on my machine" issues by ensuring local development uses the
same tool versions as CI.

Usage:
    python scripts/sync_tool_versions.py --check   # Verify alignment
    python scripts/sync_tool_versions.py --apply   # Update pyproject.toml
"""

from __future__ import annotations

import argparse
import dataclasses
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from re import Pattern

PIN_FILE = Path(".github/workflows/autofix-versions.env")
PYPROJECT_FILE = Path("pyproject.toml")


@dataclasses.dataclass(frozen=True)
class ToolConfig:
    """Metadata describing how to align a tool's version pins."""

    env_key: str
    package_name: str
    pyproject_pattern: Pattern[str]
    pyproject_format: str


def _compile(pattern: str) -> Pattern[str]:
    return re.compile(pattern, flags=re.MULTILINE)


def _format_entry(pattern: str, version: str) -> str:
    return pattern.format(version=version)


TOOL_CONFIGS: tuple[ToolConfig, ...] = (
    ToolConfig(
        env_key="RUFF_VERSION",
        package_name="ruff",
        pyproject_pattern=_compile(r'"ruff>=(?P<version>[^"]+)",?'),
        pyproject_format='"ruff>={version}",',
    ),
    ToolConfig(
        env_key="MYPY_VERSION",
        package_name="mypy",
        pyproject_pattern=_compile(r'"mypy>=(?P<version>[^"]+)",?'),
        pyproject_format='"mypy>={version}",',
    ),
    ToolConfig(
        env_key="PYTEST_VERSION",
        package_name="pytest",
        pyproject_pattern=_compile(r'"pytest>=(?P<version>[^"]+)",?'),
        pyproject_format='"pytest>={version}",',
    ),
    ToolConfig(
        env_key="PYTEST_COV_VERSION",
        package_name="pytest-cov",
        pyproject_pattern=_compile(r'"pytest-cov>=(?P<version>[^"]+)",?'),
        pyproject_format='"pytest-cov>={version}",',
    ),
)


class SyncError(RuntimeError):
    """Raised when the repository is misconfigured or a sync fails."""


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse the pin file and return a mapping of variable names to versions."""
    if not path.exists():
        raise SyncError(f"Pin file '{path}' does not exist")

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#"):
            continue
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        values[key.strip()] = raw_value.strip()

    missing = [cfg.env_key for cfg in TOOL_CONFIGS if cfg.env_key not in values]
    if missing:
        raise SyncError(f"Pin file '{path}' is missing keys: {', '.join(missing)}")
    return values


def ensure_pyproject(
    content: str, configs: Iterable[ToolConfig], env: dict[str, str], apply: bool
) -> tuple[str, dict[str, str]]:
    """Check/update pyproject.toml against pinned versions.

    Returns the (possibly updated) content and a dict of mismatches found.
    """
    mismatches: dict[str, str] = {}
    updated_content = content

    for cfg in configs:
        expected = env[cfg.env_key]
        match = cfg.pyproject_pattern.search(updated_content)
        if not match:
            # Pattern not found - might be using == instead of >=
            # Try alternative patterns
            alt_pattern = _compile(cfg.pyproject_pattern.pattern.replace(">=", "=="))
            match = alt_pattern.search(updated_content)
            if not match:
                print(f"⚠ {cfg.package_name}: not found in pyproject.toml (skipped)")
                continue

        current = match.group("version")
        # Compare major.minor version numbers
        current_parts = current.split(".")[:2]
        expected_parts = expected.split(".")[:2]

        if current_parts != expected_parts:
            mismatches[cfg.package_name] = f"pyproject has {current}, pin file has {expected}"
            if apply:
                replacement = _format_entry(cfg.pyproject_format, expected)
                updated_content = cfg.pyproject_pattern.sub(
                    lambda _m, repl=replacement: repl,
                    updated_content,
                    count=1,
                )

    return updated_content, mismatches


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Synchronise tool version pins with pyproject.toml",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Rewrite pyproject.toml to match pinned versions instead of only checking",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Explicitly run in verification-only mode (default)",
    )
    args = parser.parse_args(list(argv) if argv else [])
    apply_changes = args.apply

    if args.check and args.apply:
        parser.error("--apply and --check are mutually exclusive")
    if not args.apply:
        apply_changes = False

    try:
        env_values = parse_env_file(PIN_FILE)
    except SyncError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1

    if not PYPROJECT_FILE.exists():
        print(f"✗ {PYPROJECT_FILE} does not exist", file=sys.stderr)
        return 1

    pyproject_content = PYPROJECT_FILE.read_text(encoding="utf-8")

    pyproject_updated, project_mismatches = ensure_pyproject(
        pyproject_content, TOOL_CONFIGS, env_values, apply_changes
    )

    if project_mismatches and not apply_changes:
        print("Tool version mismatches found:")
        for package, message in project_mismatches.items():
            print(f"  ✗ {package}: {message}", file=sys.stderr)
        print(
            "\nUse --apply to rewrite pyproject.toml with the pinned versions.",
            file=sys.stderr,
        )
        return 1

    if apply_changes and pyproject_updated != pyproject_content:
        PYPROJECT_FILE.write_text(pyproject_updated, encoding="utf-8")
        print("✓ tool pins synced to pyproject.toml")
        print("Run: pip-compile --extra=dev --output-file=requirements-dev.lock pyproject.toml")
        return 0

    if not project_mismatches:
        print("✓ all tool versions are aligned")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
