"""Validate GitHub Action references and generate issue-comment-ready output."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib import error, request

import yaml

ACTION_REF_PATTERN = re.compile(
    r"^(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)@(?P<version>[^\s]+)$"
)


@dataclass(frozen=True)
class ActionValidationResult:
    """Validation details for one remote GitHub Action reference."""

    reference: str
    workflows: tuple[str, ...]
    repository_url: str
    marketplace_url: str
    version_url: str
    repository_status: int
    marketplace_status: int
    version_status: int
    repository_ok: bool
    marketplace_ok: bool
    version_ok: bool

    @property
    def is_valid(self) -> bool:
        return self.classification == "valid"

    @property
    def classification(self) -> str:
        dimensions = (
            _dimension_status(self.repository_status, self.repository_ok),
            _dimension_status(self.marketplace_status, self.marketplace_ok),
            _dimension_status(self.version_status, self.version_ok),
        )
        if all(dimension == "pass" for dimension in dimensions):
            return "valid"
        if any(dimension == "fail" for dimension in dimensions):
            return "invalid"
        return "unknown"


def _http_status(url: str, timeout: int = 10) -> int:
    req = request.Request(url, headers={"User-Agent": "travel-plan-permission-action-audit"})
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return response.status
    except error.HTTPError as exc:
        return exc.code
    except error.URLError:
        return 0


def _iter_uses_nodes(node: object) -> list[str]:
    refs: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "uses" and isinstance(value, str):
                refs.append(value)
            refs.extend(_iter_uses_nodes(value))
    elif isinstance(node, list):
        for item in node:
            refs.extend(_iter_uses_nodes(item))
    return refs


def _is_remote_action_reference(reference: str) -> bool:
    if reference.startswith("./"):
        return False
    if reference.startswith("docker://"):
        return False
    return bool(ACTION_REF_PATTERN.match(reference))


def collect_action_references(workflow_paths: list[Path]) -> dict[str, tuple[str, ...]]:
    mapping: dict[str, set[str]] = {}
    for workflow_path in workflow_paths:
        if not workflow_path.exists():
            raise FileNotFoundError(f"Workflow file not found: {workflow_path}")
        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        for reference in _iter_uses_nodes(workflow):
            if not _is_remote_action_reference(reference):
                continue
            mapping.setdefault(reference, set()).add(workflow_path.as_posix())

    return {reference: tuple(sorted(paths)) for reference, paths in sorted(mapping.items())}


def _status_ok(status_code: int) -> bool:
    return 200 <= status_code < 400


def _dimension_status(status_code: int, ok: bool) -> str:
    if ok:
        return "pass"
    if status_code == 0:
        return "unknown"
    return "fail"


def _dimension_label(ok: bool, status_code: int) -> str:
    if ok:
        return "PASS"
    if status_code == 0:
        return "UNVERIFIED"
    return "FAIL"


def validate_action_reference(
    reference: str,
    workflows: tuple[str, ...],
    fetch_status: Callable[[str], int] = _http_status,
) -> ActionValidationResult:
    match = ACTION_REF_PATTERN.match(reference)
    if match is None:
        raise ValueError(f"Invalid action reference format: {reference}")

    owner = match.group("owner")
    repo = match.group("repo")
    version = match.group("version")

    repository_url = f"https://api.github.com/repos/{owner}/{repo}"
    marketplace_url = f"https://github.com/marketplace/actions/{repo}"
    tag_url = f"https://api.github.com/repos/{owner}/{repo}/git/ref/tags/{version}"
    branch_url = f"https://api.github.com/repos/{owner}/{repo}/branches/{version}"

    repository_status = fetch_status(repository_url)
    repository_ok = _status_ok(repository_status)
    marketplace_status = fetch_status(marketplace_url)
    marketplace_ok = _status_ok(marketplace_status)

    version_status = fetch_status(tag_url)
    version_url = tag_url
    version_ok = _status_ok(version_status)
    if not version_ok:
        branch_status = fetch_status(branch_url)
        version_url = branch_url
        version_ok = _status_ok(branch_status)

    return ActionValidationResult(
        reference=reference,
        workflows=workflows,
        repository_url=repository_url,
        marketplace_url=marketplace_url,
        version_url=version_url,
        repository_status=repository_status,
        marketplace_status=marketplace_status,
        version_status=version_status,
        repository_ok=repository_ok,
        marketplace_ok=marketplace_ok,
        version_ok=version_ok,
    )


def build_validation_report(
    workflow_paths: list[Path], fetch_status: Callable[[str], int] = _http_status
) -> dict[str, object]:
    references = collect_action_references(workflow_paths)
    validations = [
        validate_action_reference(reference, workflows, fetch_status=fetch_status)
        for reference, workflows in references.items()
    ]

    results = [
        {
            "reference": result.reference,
            "workflows": list(result.workflows),
            "repository_url": result.repository_url,
            "marketplace_url": result.marketplace_url,
            "version_url": result.version_url,
            "repository_status": result.repository_status,
            "marketplace_status": result.marketplace_status,
            "version_status": result.version_status,
            "repository_ok": result.repository_ok,
            "marketplace_ok": result.marketplace_ok,
            "version_ok": result.version_ok,
            "valid": result.is_valid,
            "classification": result.classification,
        }
        for result in validations
    ]

    valid_count = sum(1 for result in validations if result.is_valid)
    invalid_count = sum(1 for result in validations if result.classification == "invalid")
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "workflows": [path.as_posix() for path in workflow_paths],
        "results": results,
        "summary": {
            "total_references": len(results),
            "valid_references": valid_count,
            "invalid_references": invalid_count,
            "unknown_references": len(results) - valid_count - invalid_count,
        },
    }


def build_comment_report(report: dict[str, object]) -> str:
    summary = report["summary"]
    results = report["results"]

    lines = [
        "## GitHub Action Reference Validation",
        "",
        f"- Generated (UTC): `{report['generated_at_utc']}`",
        f"- Workflows scanned: `{', '.join(report['workflows'])}`",
        f"- Total references: {summary['total_references']}",
        f"- Valid references: {summary['valid_references']}",
        f"- Invalid references: {summary['invalid_references']}",
        f"- Unknown references: {summary['unknown_references']}",
        "",
        "| Action reference | Workflow files | Repository | Marketplace | Version ref | Result |",
        "|---|---|---|---|---|---|",
    ]

    for result in results:
        status = {
            "valid": "VALID",
            "invalid": "REVIEW",
            "unknown": "UNVERIFIED",
        }[result["classification"]]
        workflows = "<br>".join(result["workflows"])
        repository = _dimension_label(
            result["repository_ok"], status_code=result["repository_status"]
        )
        marketplace = _dimension_label(
            result["marketplace_ok"], status_code=result["marketplace_status"]
        )
        version = _dimension_label(result["version_ok"], status_code=result["version_status"])
        lines.append(
            "| "
            f"`{result['reference']}` | {workflows} | {repository} | {marketplace} | {version} | {status} |"
        )

    if summary["invalid_references"] or summary["unknown_references"]:
        lines.extend(
            [
                "",
                "### Needs human",
                "One or more action references did not validate cleanly or could not be verified.",
                "Review FAIL and UNVERIFIED columns and rerun from a network-enabled environment.",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate GitHub Action references and emit issue-comment-ready output."
    )
    parser.add_argument(
        "--workflow",
        action="append",
        dest="workflows",
        help="Workflow file to scan (repeatable).",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON report to stdout.")
    parser.add_argument(
        "--comment",
        action="store_true",
        help="Print comment-ready markdown report to stdout.",
    )
    parser.add_argument("--output", help="Write JSON report to the provided path.")
    parser.add_argument(
        "--comment-output",
        help="Write comment-ready markdown report to the provided path.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero when one or more action references fail validation.",
    )
    args = parser.parse_args(argv)

    workflow_args = args.workflows or [
        ".github/workflows/ci.yml",
        ".github/workflows/pr-00-gate.yml",
    ]
    workflow_paths = [Path(path) for path in workflow_args]

    try:
        report = build_validation_report(workflow_paths)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    invalid_count = report["summary"]["invalid_references"]

    if args.output:
        Path(args.output).write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    if args.comment_output:
        Path(args.comment_output).write_text(build_comment_report(report), encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    elif args.comment:
        print(build_comment_report(report).rstrip())
    else:
        print(
            f"Validated {report['summary']['total_references']} references "
            f"({report['summary']['invalid_references']} invalid)."
        )

    if args.check and invalid_count:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
