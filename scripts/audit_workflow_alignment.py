"""Compare local workflow files with the Workflows repo snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
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


def build_workflow_report(local_root: Path, workflows_root: Path) -> dict[str, object]:
    missing, extra, modified = compare_workflow_trees(local_root, workflows_root)
    return {
        "local_root": str(local_root),
        "workflows_root": str(workflows_root),
        "missing": missing,
        "extra": extra,
        "modified": modified,
        "summary": {
            "missing": len(missing),
            "extra": len(extra),
            "modified": len(modified),
        },
    }


def write_json_report(report: dict[str, object], output_path: Path) -> None:
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_markdown_report(report: dict[str, object]) -> str:
    summary = report["summary"]
    missing = report["missing"]
    extra = report["extra"]
    modified = report["modified"]

    lines = [
        "# Workflow alignment report",
        "",
        f"Local root: `{report['local_root']}`",
        f"Workflows root: `{report['workflows_root']}`",
        "",
        "## Summary",
        f"- Missing: {summary['missing']}",
        f"- Extra: {summary['extra']}",
        f"- Modified: {summary['modified']}",
        "",
    ]

    def add_section(title: str, items: list[str]) -> None:
        lines.append(f"## {title}")
        if items:
            lines.extend(f"- {item}" for item in items)
        else:
            lines.append("- None")
        lines.append("")

    add_section("Missing workflows", missing)
    add_section("Extra workflows", extra)
    add_section("Modified workflows", modified)

    if missing or extra or modified:
        lines.extend(
            [
                "## Needs human",
                "Workflow files differ from the Workflows repo snapshot. Aligning them requires",
                "updating `.github/workflows/**`, which needs agent-high-privilege access.",
                "",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


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
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON report to stdout.",
    )
    parser.add_argument(
        "--markdown",
        action="store_true",
        help="Print markdown report to stdout.",
    )
    parser.add_argument(
        "--output",
        help="Write JSON report to the provided path.",
    )
    parser.add_argument(
        "--markdown-output",
        help="Write markdown report to the provided path.",
    )
    args = parser.parse_args(argv)

    try:
        report = build_workflow_report(Path(args.local), Path(args.workflows))
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    missing = report["missing"]
    extra = report["extra"]
    modified = report["modified"]

    if args.output:
        write_json_report(report, Path(args.output))

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        if args.check and (missing or extra or modified):
            return 1
        return 0
    if args.markdown or args.markdown_output:
        markdown = build_markdown_report(report)
        if args.markdown_output:
            Path(args.markdown_output).write_text(markdown, encoding="utf-8")
        if args.markdown:
            print(markdown.rstrip())
        if args.check and (missing or extra or modified):
            return 1
        return 0

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
