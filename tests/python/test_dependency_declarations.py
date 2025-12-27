"""Tests for ensuring dependencies are declared in pyproject.toml."""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

MODULE_TO_DEPENDENCY = {
    "pil": "pillow",
    "yaml": "pyyaml",
}


def _iter_package_files() -> list[Path]:
    package_root = Path(__file__).resolve().parents[2] / "src" / "travel_plan_permission"
    return list(package_root.rglob("*.py"))


def _extract_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module is None or node.level:
                continue
            modules.add(node.module.split(".")[0])
    return modules


def _load_declared_dependencies() -> set[str]:
    pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
    pyproject_data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = pyproject_data["project"]
    dependencies = project["dependencies"]
    optional_dependencies = project.get("optional-dependencies", {})
    names = set()
    for dependency in dependencies:
        name = re.split(r"[<>=!~\\[]", dependency, maxsplit=1)[0].strip()
        if name:
            names.add(name.lower())
    for extra_dependencies in optional_dependencies.values():
        for dependency in extra_dependencies:
            name = re.split(r"[<>=!~\\[]", dependency, maxsplit=1)[0].strip()
            if name:
                names.add(name.lower())
    return names


def test_dependencies_are_declared() -> None:
    """All third-party imports should be listed in pyproject.toml."""
    stdlib_modules = sys.stdlib_module_names
    declared = _load_declared_dependencies()
    imported_modules: set[str] = set()

    for path in _iter_package_files():
        imported_modules.update(_extract_modules(path))

    third_party_modules = {
        module
        for module in imported_modules
        if module not in stdlib_modules and module != "travel_plan_permission"
    }
    normalized = {
        MODULE_TO_DEPENDENCY.get(module.lower(), module.lower())
        for module in third_party_modules
    }
    missing = sorted(normalized - declared)

    assert not missing, f"Missing dependency declarations for: {', '.join(missing)}"
