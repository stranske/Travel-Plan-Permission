"""Compare local workflow files with the Workflows repo snapshot."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path


def _hash_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def collect_workflow_files(root: Path) -> dict[str, str]:
    if not root.exists():
        raise FileNotFoundError(f"Workflow directory not found: {root}")
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            files[relative] = _hash_file(path)
    return files


def compare_workflow_trees(
    local_root: Path, workflows_root: Path
) -> tuple[list[str], list[str], list[str]]:
    local_files = collect_workflow_files(local_root)
    workflows_files = collect_workflow_files(workflows_root)

    local_set = set(local_files)
    workflows_set = set(workflows_files)

    missing = sorted(workflows_set - local_set)
    extra = sorted(local_set - workflows_set)
    modified = sorted(
        name for name in local_set & workflows_set if local_files[name] != workflows_files[name]
    )

    return missing, extra, modified


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare .github/workflows with .workflows-lib snapshot."
    )
    parser.add_argument(
        "--local",
        default=".github/workflows",
        help="Local workflow directory to compare.",
    )
    parser.add_argument(
        "--workflows",
        default=".workflows-lib/.github/workflows",
        help="Workflows repo snapshot directory to compare against.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero when differences are found.",
    )
    args = parser.parse_args(argv)

    try:
        missing, extra, modified = compare_workflow_trees(Path(args.local), Path(args.workflows))
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if missing:
        print("Missing workflows:")
        print("\n".join(f"- {name}" for name in missing))
    if extra:
        print("Extra workflows:")
        print("\n".join(f"- {name}" for name in extra))
    if modified:
        print("Modified workflows:")
        print("\n".join(f"- {name}" for name in modified))

    if not missing and not extra and not modified:
        print("Workflow structure matches Workflows repo snapshot.")

    if args.check and (missing or extra or modified):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
