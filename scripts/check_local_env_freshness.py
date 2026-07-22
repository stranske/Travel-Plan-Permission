#!/usr/bin/env python3
"""Check a local virtualenv against pyproject dev deps and requirements.lock."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PYTHON = Path(".venv/bin/python")


@dataclass(frozen=True)
class RequirementTarget:
    name: str
    specs: tuple[tuple[str, str], ...]
    source: str


@dataclass(frozen=True)
class InstalledPackage:
    name: str
    version: str | None


def normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_requirement_name(requirement: str) -> str | None:
    text = requirement.split("#", 1)[0].split(";", 1)[0].strip()
    if not text:
        return None
    match = re.match(r"^\s*([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?", text)
    if not match:
        return None
    return normalize_name(match.group(1))


def parse_requirement_specs(requirement: str) -> tuple[tuple[str, str], ...]:
    text = requirement.split("#", 1)[0].split(";", 1)[0]
    specs: list[tuple[str, str]] = []
    for match in re.finditer(r"(==|>=)\s*([A-Za-z0-9_.!*+\-]+)", text):
        specs.append((match.group(1), match.group(2)))
    return tuple(specs)


def load_pyproject_extra(pyproject: Path, extra: str) -> dict[str, tuple[tuple[str, str], ...]]:
    data = tomllib.loads(pyproject.read_text())
    raw_deps = data.get("project", {}).get("optional-dependencies", {}).get(extra, [])
    deps: dict[str, tuple[tuple[str, str], ...]] = {}
    for req in raw_deps:
        name = parse_requirement_name(str(req))
        if name:
            deps[name] = parse_requirement_specs(str(req))
    return deps


def load_lock_versions(lockfile: Path) -> dict[str, str]:
    versions: dict[str, str] = {}
    if not lockfile.exists():
        return versions
    for line in lockfile.read_text().splitlines():
        text = line.strip()
        if not text or text.startswith("#") or text.startswith("-"):
            continue
        match = re.match(r"^([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?==([^\s;]+)", text)
        if match:
            versions[normalize_name(match.group(1))] = match.group(2)
    return versions


def collect_targets(pyproject: Path, lockfile: Path, extra: str) -> list[RequirementTarget]:
    extra_deps = load_pyproject_extra(pyproject, extra)
    lock_versions = load_lock_versions(lockfile)
    targets: list[RequirementTarget] = []
    for name, specs in sorted(extra_deps.items()):
        if name in lock_versions:
            targets.append(
                RequirementTarget(
                    name=name, specs=(("==", lock_versions[name]),), source=str(lockfile)
                )
            )
        elif specs:
            targets.append(RequirementTarget(name=name, specs=specs, source=str(pyproject)))
    return targets


def installed_versions(python: Path, package_names: list[str]) -> dict[str, InstalledPackage]:
    code = r"""
import json
import sys
from importlib.metadata import PackageNotFoundError, version

result = {}
for name in sys.argv[1:]:
    try:
        result[name] = version(name)
    except PackageNotFoundError:
        result[name] = None
print(json.dumps(result, sort_keys=True))
"""
    proc = subprocess.run(
        [str(python), "-c", code, *package_names],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"{python} failed")
    raw = json.loads(proc.stdout)
    return {
        normalize_name(name): InstalledPackage(name=normalize_name(name), version=version)
        for name, version in raw.items()
    }


def version_key(version: str) -> tuple[object, ...]:
    parts: list[object] = []
    for part in re.split(r"[.\-+_]", version):
        if part.isdigit():
            parts.append(int(part))
        else:
            match = re.match(r"^(\d+)(.*)$", part)
            if match:
                parts.append(int(match.group(1)))
                if match.group(2):
                    parts.append(match.group(2))
            elif part:
                parts.append(part)
    return tuple(parts)


def version_satisfies(installed: str, specs: tuple[tuple[str, str], ...]) -> bool:
    for op, expected in specs:
        if op == "==" and installed != expected:
            return False
        if op == ">=" and version_key(installed) < version_key(expected):
            return False
    return True


def suggested_refresh_command(python: Path, lockfile: Path) -> str:
    if lockfile.exists():
        return f"uv pip install --python {python} -r {lockfile}"
    return f"uv pip install --python {python} -e '.[dev]'"


def check_environment(pyproject: Path, lockfile: Path, python: Path, extra: str) -> int:
    if not pyproject.exists():
        print(f"Missing {pyproject}; run from the repository root.", file=sys.stderr)
        return 2
    if not python.exists():
        print(f"Missing {python}; create the local environment first.", file=sys.stderr)
        print(
            f"Suggested setup: python -m venv .venv && {suggested_refresh_command(python, lockfile)}",
            file=sys.stderr,
        )
        return 2

    targets = collect_targets(pyproject, lockfile, extra)
    if not targets:
        print(f"No optional dependency targets found for extra '{extra}'.")
        return 0

    try:
        installed = installed_versions(python, [target.name for target in targets])
    except RuntimeError as exc:
        print(f"Could not inspect {python}: {exc}", file=sys.stderr)
        return 2

    problems: list[str] = []
    for target in targets:
        current = installed.get(target.name, InstalledPackage(target.name, None)).version
        expected = ", ".join(f"{op}{version}" for op, version in target.specs)
        if current is None:
            problems.append(f"- {target.name}: missing, expected {expected} from {target.source}")
        elif not version_satisfies(current, target.specs):
            problems.append(
                f"- {target.name}: installed {current}, expected {expected} from {target.source}"
            )

    if problems:
        print("Local Python environment is stale or incomplete:", file=sys.stderr)
        print("\n".join(problems), file=sys.stderr)
        print(f"\nRefresh it with: {suggested_refresh_command(python, lockfile)}", file=sys.stderr)
        return 1

    print(
        f"Local Python environment matches {lockfile if lockfile.exists() else pyproject} for extra '{extra}'."
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Check the selected interpreter and fail on drift."
    )
    parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--lockfile", type=Path, default=Path("requirements.lock"))
    parser.add_argument("--python", type=Path, default=DEFAULT_PYTHON)
    parser.add_argument("--extra", default="dev", help="Optional dependency extra to check.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.check:
        parser.print_help()
        return 0
    return check_environment(args.pyproject, args.lockfile, args.python, args.extra)


if __name__ == "__main__":
    raise SystemExit(main())
