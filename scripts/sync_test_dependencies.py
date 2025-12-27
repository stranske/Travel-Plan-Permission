#!/usr/bin/env python3
"""Synchronise test imports with the dependency declarations in pyproject.toml.

This script scans test files for imports and ensures they are declared in
pyproject.toml's dev dependencies. It can auto-fix missing dependencies.

Usage:
    python scripts/sync_test_dependencies.py           # Check for missing
    python scripts/sync_test_dependencies.py --fix     # Auto-add missing
    python scripts/sync_test_dependencies.py --verify  # CI mode (exit 1 if missing)
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path
from typing import Any, cast

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[import-not-found]

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_FILE = REPO_ROOT / "pyproject.toml"
TESTS_DIR = REPO_ROOT / "tests"
DEV_EXTRA = "dev"

# Try to import tomlkit for editing (optional)
TOMLKIT_ERROR: ImportError | None
try:
    import tomlkit
except ImportError as exc:
    TOMLKIT_ERROR = exc
    tomlkit = None  # type: ignore[assignment]
else:
    TOMLKIT_ERROR = None

# Standard library modules that don't need to be installed
STDLIB_MODULES = {
    "abc",
    "argparse",
    "ast",
    "asyncio",
    "base64",
    "builtins",
    "collections",
    "contextlib",
    "configparser",
    "copy",
    "csv",
    "datetime",
    "decimal",
    "enum",
    "fractions",
    "functools",
    "gc",
    "glob",
    "hashlib",
    "importlib",
    "inspect",
    "io",
    "itertools",
    "json",
    "logging",
    "math",
    "multiprocessing",
    "os",
    "pathlib",
    "pickle",
    "platform",
    "random",
    "re",
    "shlex",
    "shutil",
    "signal",
    "socket",
    "stat",
    "string",
    "struct",
    "subprocess",
    "sys",
    "tempfile",
    "textwrap",
    "threading",
    "time",
    "tomllib",
    "traceback",
    "types",
    "typing",
    "unittest",
    "urllib",
    "uuid",
    "warnings",
    "weakref",
    "xml",
    "zipfile",
    "__future__",
    "dataclasses",
    "pprint",
    "typing_extensions",
}

# Known test framework modules
TEST_FRAMEWORK_MODULES = {
    "pytest",
    "hypothesis",
    "_pytest",
    "pluggy",
}

# Project modules (installed via `pip install -e .`)
PROJECT_MODULES = {
    "travel_plan_permission",
    "src",
    "tests",
}

# Module name to package name mappings
MODULE_TO_PACKAGE = {
    "yaml": "PyYAML",
    "PIL": "Pillow",
    "sklearn": "scikit-learn",
    "cv2": "opencv-python",
    "tomli": "tomli",
}


def _normalize_module_name(module: str) -> str:
    return module.replace("-", "_").lower()


def _normalise_package_name(package: str) -> str:
    """Normalise package identifiers for set comparisons."""
    return _normalize_module_name(package)


_SPECIFIER_PATTERN = re.compile(r"[!=<>~]")


def _extract_requirement_name(entry: str) -> str | None:
    """Return the canonical package name for a requirement entry."""
    cleaned = entry.split(";")[0].strip().strip(",")
    if not cleaned:
        return None

    token = cleaned.split()[0]
    if not token:
        return None

    token = token.split("[", maxsplit=1)[0]
    token = _SPECIFIER_PATTERN.split(token, maxsplit=1)[0]

    return token or None


def extract_imports_from_file(file_path: Path) -> set[str]:
    """Extract all top-level import names from a Python file."""
    imports: set[str] = set()

    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(file_path))
    except (SyntaxError, UnicodeDecodeError):
        return imports

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top_level = alias.name.split(".")[0]
                imports.add(top_level)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_level = node.module.split(".")[0]
            imports.add(top_level)

    return imports


def get_all_test_imports() -> set[str]:
    """Get all imports used across all test files."""
    all_imports: set[str] = set()

    if not TESTS_DIR.exists():
        return all_imports

    for py_file in TESTS_DIR.rglob("*.py"):
        all_imports.update(extract_imports_from_file(py_file))

    return all_imports


def get_declared_dependencies() -> tuple[set[str], dict[str, list[str]]]:
    """Return declared dependency module names and raw dependency groups."""
    if not PYPROJECT_FILE.exists():
        return set(), {}

    data = tomllib.loads(PYPROJECT_FILE.read_text(encoding="utf-8"))
    project = data.get("project", {})

    declared: set[str] = set()
    groups: dict[str, list[str]] = {}

    for entry in project.get("dependencies", []):
        package = entry.split(";")[0].strip().strip(",")
        if package:
            groups.setdefault("dependencies", []).append(package)
            name = _extract_requirement_name(package)
            if name:
                declared.add(_normalise_package_name(name))

    for group, entries in project.get("optional-dependencies", {}).items():
        groups[group] = list(entries)
        for entry in entries:
            name = _extract_requirement_name(entry)
            if name:
                declared.add(_normalise_package_name(name))

    return declared, groups


def find_missing_dependencies() -> set[str]:
    """Find imports that are not declared as dependencies."""
    declared, _ = get_declared_dependencies()
    all_imports = get_all_test_imports()

    potential = all_imports - STDLIB_MODULES - TEST_FRAMEWORK_MODULES - PROJECT_MODULES

    missing: set[str] = set()
    for import_name in potential:
        package_name = MODULE_TO_PACKAGE.get(import_name, import_name)
        normalised = _normalise_package_name(package_name)
        if normalised not in declared:
            missing.add(package_name)

    return missing


def add_dependencies_to_pyproject(missing: set[str], fix: bool = False) -> bool:
    """Add missing dependencies to the dev extra inside pyproject.toml."""
    if not missing or not fix:
        return False

    if TOMLKIT_ERROR is not None or tomlkit is None:
        print(
            "⚠ tomlkit is required to update pyproject.toml automatically.\n"
            "  Install with: pip install tomlkit\n"
            "  Then retry, or manually add the dependencies to [project.optional-dependencies.dev]"
        )
        return False

    document = tomlkit.parse(PYPROJECT_FILE.read_text(encoding="utf-8"))

    project = cast(Any, document["project"])
    optional = project.setdefault("optional-dependencies", tomlkit.table())
    dev_group = optional.get(DEV_EXTRA)
    if dev_group is None:
        dev_group = tomlkit.array()
        dev_group.multiline(True)
        optional[DEV_EXTRA] = dev_group

    existing_normalised = {
        _normalise_package_name(str(item).split("[")[0]) for item in dev_group
    }

    added = False
    for package in sorted(missing):
        normalised = _normalise_package_name(package)
        if normalised in existing_normalised:
            continue
        dev_group.append(package)
        existing_normalised.add(normalised)
        added = True

    if added:
        PYPROJECT_FILE.write_text(tomlkit.dumps(document), encoding="utf-8")

    return added


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Sync test dependencies to pyproject.toml"
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Update the dev extra in pyproject.toml with missing dependencies",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Exit with code 1 if changes are needed (for CI)",
    )
    args = parser.parse_args(argv)

    missing = find_missing_dependencies()

    if not missing:
        print("✅ All test dependencies are declared in pyproject.toml")
        return 0

    print(f"⚠️  Found {len(missing)} undeclared dependencies:")
    for dep in sorted(missing):
        print(f"  - {dep}")

    if args.fix:
        added = add_dependencies_to_pyproject(missing, fix=True)
        if added:
            print("\n✅ Added dependencies to [project.optional-dependencies.dev]")
            print(
                "Please run: pip-compile --extra=dev --output-file=requirements-dev.lock pyproject.toml"
            )
        else:
            print("\nℹ️  Dependencies already declared in dev extra")
        return 0

    if args.verify:
        print("\n❌ Run: python scripts/sync_test_dependencies.py --fix")
        return 1

    print("\nTo fix, run: python scripts/sync_test_dependencies.py --fix")
    return 0


if __name__ == "__main__":
    sys.exit(main())
