"""Audit LangGraph workflow pytest targets and their prefer_langgraph coverage."""

from __future__ import annotations

import argparse
import ast
import json
import shlex
from dataclasses import dataclass
from pathlib import Path

import yaml

LANGGRAPH_TEST_STEP_NAME = "Run LangGraph orchestration tests"


@dataclass(frozen=True)
class LangGraphTargetResult:
    """Validation details for one pytest target referenced by a workflow."""

    workflow: str
    job_id: str
    job_name: str
    target: str
    target_file: str
    scope: str | None
    file_exists: bool
    prefer_langgraph_true: bool


def _extract_pytest_targets(command: str) -> list[str]:
    targets: list[str] = []
    for raw_line in command.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        normalized = line.rstrip("\\").strip()
        if not normalized:
            continue
        parts = shlex.split(normalized, comments=True)
        for part in parts:
            if part == "pytest" or part.startswith("-"):
                continue
            targets.append(part)
    return targets


def _test_targets_from_run_step(command: str) -> list[str]:
    return [target for target in _extract_pytest_targets(command) if ".py" in target]


def _find_named_scope(tree: ast.Module, scope_name: str) -> ast.AST | None:
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == scope_name:
            return node
        if isinstance(node, ast.ClassDef) and node.name == scope_name:
            return node
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == scope_name:
            return node
    return None


def _function_calls_prefer_langgraph_true(fn_node: ast.AST) -> bool:
    for node in ast.walk(fn_node):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if (
                keyword.arg == "prefer_langgraph"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
            ):
                return True
    return False


def _target_uses_prefer_langgraph_true(*, target_file: Path, scope_name: str | None) -> bool:
    tree = ast.parse(target_file.read_text(encoding="utf-8"))
    if scope_name is None:
        return _function_calls_prefer_langgraph_true(tree)
    scope = _find_named_scope(tree, scope_name)
    if scope is None:
        return False
    return _function_calls_prefer_langgraph_true(scope)


def collect_langgraph_runtime_targets(
    workflow_paths: list[Path], *, repo_root: Path
) -> list[LangGraphTargetResult]:
    results: list[LangGraphTargetResult] = []

    for workflow_path in workflow_paths:
        if not workflow_path.exists():
            raise FileNotFoundError(f"Workflow file not found: {workflow_path}")

        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        jobs = workflow.get("jobs", {})
        for job_id, job in jobs.items():
            if not isinstance(job, dict):
                continue
            job_name = str(job.get("name", job_id))
            steps = job.get("steps", [])
            if not isinstance(steps, list):
                continue

            for step in steps:
                if not isinstance(step, dict):
                    continue
                if step.get("name") != LANGGRAPH_TEST_STEP_NAME:
                    continue
                run_command = step.get("run")
                if not isinstance(run_command, str):
                    continue

                for target in _test_targets_from_run_step(run_command):
                    target_parts = target.split("::")
                    relative_file = target_parts[0]
                    target_file = repo_root / relative_file
                    scope = target_parts[-1] if len(target_parts) > 1 else None
                    file_exists = target_file.exists()
                    prefer_langgraph_true = (
                        _target_uses_prefer_langgraph_true(
                            target_file=target_file,
                            scope_name=scope,
                        )
                        if file_exists
                        else False
                    )
                    results.append(
                        LangGraphTargetResult(
                            workflow=workflow_path.as_posix(),
                            job_id=str(job_id),
                            job_name=job_name,
                            target=target,
                            target_file=relative_file,
                            scope=scope,
                            file_exists=file_exists,
                            prefer_langgraph_true=prefer_langgraph_true,
                        )
                    )

    return results


def build_runtime_report(workflow_paths: list[Path], *, repo_root: Path) -> dict[str, object]:
    results = collect_langgraph_runtime_targets(workflow_paths, repo_root=repo_root)
    payload_results = [
        {
            "workflow": result.workflow,
            "job_id": result.job_id,
            "job_name": result.job_name,
            "target": result.target,
            "target_file": result.target_file,
            "scope": result.scope,
            "file_exists": result.file_exists,
            "prefer_langgraph_true": result.prefer_langgraph_true,
        }
        for result in results
    ]
    return {
        "workflows": [path.as_posix() for path in workflow_paths],
        "summary": {
            "total_targets": len(payload_results),
            "existing_targets": sum(1 for result in results if result.file_exists),
            "prefer_langgraph_targets": sum(
                1 for result in results if result.prefer_langgraph_true
            ),
        },
        "results": payload_results,
    }


def build_comment_report(report: dict[str, object]) -> str:
    summary = report["summary"]
    lines = [
        "## LangGraph Runtime Test Target Audit",
        "",
        f"- Workflows scanned: `{', '.join(report['workflows'])}`",
        f"- Total targets: {summary['total_targets']}",
        f"- Existing targets: {summary['existing_targets']}",
        f"- Targets with `prefer_langgraph=True` path: {summary['prefer_langgraph_targets']}",
        "",
        "| Workflow | Job | Pytest target | File exists | `prefer_langgraph=True` path |",
        "|---|---|---|---|---|",
    ]

    for result in report["results"]:
        file_status = "YES" if result["file_exists"] else "NO"
        prefer_status = "YES" if result["prefer_langgraph_true"] else "NO"
        lines.append(
            "| "
            f"`{result['workflow']}` | `{result['job_id']}` | `{result['target']}` | "
            f"{file_status} | {prefer_status} |"
        )

    return "\n".join(lines).rstrip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workflow",
        action="append",
        default=[],
        help="Workflow path to scan. Can be repeated.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        help="Repository root used to resolve test paths.",
    )
    parser.add_argument(
        "--format",
        choices=("json", "comment"),
        default="json",
        help="Output format.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workflow_paths = (
        [Path(path) for path in args.workflow]
        if args.workflow
        else [Path(".github/workflows/ci.yml"), Path(".github/workflows/pr-00-gate.yml")]
    )
    report = build_runtime_report(workflow_paths, repo_root=args.repo_root.resolve())

    if args.format == "comment":
        print(build_comment_report(report), end="")
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
