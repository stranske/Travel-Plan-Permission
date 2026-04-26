"""Audit CI runtime logs for LangGraph-path test execution evidence."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

LANGGRAPH_TEST_STEP_NAME = "Run LangGraph orchestration tests"
DEFAULT_REQUIRED_TARGETS = (
    "tests/orchestration_graph_test.py",
    "tests/python/test_langgraph_orchestration.py",
    "tests/python/test_orchestration_smoke.py::test_policy_graph_langgraph_smoke",
    "tests/python/test_orchestration_smoke.py::test_policy_graph_prefers_langgraph_when_available",
)


@dataclass(frozen=True)
class RuntimeLogAuditResult:
    """Validation details for one CI log file."""

    log_path: str
    has_step_marker: bool
    command_includes_targets: bool
    passed_all_targets: bool
    missing_command_targets: tuple[str, ...]
    missing_pass_targets: tuple[str, ...]
    step_evidence: str | None
    command_evidence: str | None
    pass_evidence: dict[str, str]


def _find_first_line_with_pattern(log_text: str, pattern: re.Pattern[str]) -> str | None:
    for line in log_text.splitlines():
        if pattern.search(line):
            return line.strip()
    return None


def _collect_pytest_command_lines(log_text: str) -> list[str]:
    command_lines: list[str] = []
    for line in log_text.splitlines():
        trimmed = line.strip()
        if "pytest " in trimmed or trimmed.startswith("pytest "):
            command_lines.append(trimmed)
    return command_lines


def _line_contains_target(line: str, target: str) -> bool:
    return target in line


def _find_pass_line(log_text: str, target: str) -> str | None:
    pattern = re.compile(rf"{re.escape(target)}\s+PASSED\b")
    return _find_first_line_with_pattern(log_text, pattern)


def audit_runtime_log(
    log_path: Path, *, required_targets: tuple[str, ...]
) -> RuntimeLogAuditResult:
    if not log_path.exists():
        raise FileNotFoundError(f"Log file not found: {log_path}")

    log_text = log_path.read_text(encoding="utf-8")
    step_pattern = re.compile(re.escape(LANGGRAPH_TEST_STEP_NAME))
    step_evidence = _find_first_line_with_pattern(log_text, step_pattern)
    has_step_marker = step_evidence is not None

    command_lines = _collect_pytest_command_lines(log_text)
    command_evidence = command_lines[0] if command_lines else None
    missing_command_targets = tuple(
        target
        for target in required_targets
        if not any(_line_contains_target(line, target) for line in command_lines)
    )
    command_includes_targets = not missing_command_targets

    pass_evidence = {}
    missing_pass_targets: list[str] = []
    for target in required_targets:
        evidence = _find_pass_line(log_text, target)
        if evidence is None:
            missing_pass_targets.append(target)
            continue
        pass_evidence[target] = evidence

    return RuntimeLogAuditResult(
        log_path=log_path.as_posix(),
        has_step_marker=has_step_marker,
        command_includes_targets=command_includes_targets,
        passed_all_targets=not missing_pass_targets,
        missing_command_targets=missing_command_targets,
        missing_pass_targets=tuple(missing_pass_targets),
        step_evidence=step_evidence,
        command_evidence=command_evidence,
        pass_evidence=pass_evidence,
    )


def build_runtime_log_report(
    log_paths: list[Path], *, required_targets: tuple[str, ...]
) -> dict[str, object]:
    results = [audit_runtime_log(path, required_targets=required_targets) for path in log_paths]
    payload_results = [
        {
            "log_path": result.log_path,
            "has_step_marker": result.has_step_marker,
            "command_includes_targets": result.command_includes_targets,
            "passed_all_targets": result.passed_all_targets,
            "missing_command_targets": list(result.missing_command_targets),
            "missing_pass_targets": list(result.missing_pass_targets),
            "step_evidence": result.step_evidence,
            "command_evidence": result.command_evidence,
            "pass_evidence": result.pass_evidence,
        }
        for result in results
    ]
    return {
        "required_targets": list(required_targets),
        "summary": {
            "total_logs": len(payload_results),
            "logs_with_step_marker": sum(1 for result in results if result.has_step_marker),
            "logs_with_command_targets": sum(
                1 for result in results if result.command_includes_targets
            ),
            "logs_with_all_targets_passed": sum(
                1 for result in results if result.passed_all_targets
            ),
        },
        "results": payload_results,
    }


def build_comment_report(report: dict[str, object]) -> str:
    summary = report["summary"]
    lines = [
        "## LangGraph CI Runtime Log Audit",
        "",
        f"- Required targets: `{', '.join(report['required_targets'])}`",
        f"- Logs scanned: {summary['total_logs']}",
        f"- Logs with LangGraph test step marker: {summary['logs_with_step_marker']}",
        f"- Logs with full pytest target command: {summary['logs_with_command_targets']}",
        f"- Logs with all required targets passing: {summary['logs_with_all_targets_passed']}",
        "",
        "| Log | Step marker | Command includes targets | All targets passed |",
        "|---|---|---|---|",
    ]
    for result in report["results"]:
        step = "YES" if result["has_step_marker"] else "NO"
        command = "YES" if result["command_includes_targets"] else "NO"
        passed = "YES" if result["passed_all_targets"] else "NO"
        lines.append(f"| `{result['log_path']}` | {step} | {command} | {passed} |")
        if result["step_evidence"]:
            lines.append(f"- Step evidence: `{result['step_evidence']}`")
        if result["command_evidence"]:
            lines.append(f"- Command evidence: `{result['command_evidence']}`")
        for target, evidence in result["pass_evidence"].items():
            lines.append(f"- Pass evidence ({target}): `{evidence}`")
        if result["missing_command_targets"]:
            lines.append(
                "- Missing command targets: "
                + ", ".join(f"`{target}`" for target in result["missing_command_targets"])
            )
        if result["missing_pass_targets"]:
            lines.append(
                "- Missing pass targets: "
                + ", ".join(f"`{target}`" for target in result["missing_pass_targets"])
            )
    return "\n".join(lines).rstrip() + "\n"


def is_report_passing(report: dict[str, object]) -> bool:
    summary = report["summary"]
    return (
        summary["total_logs"] > 0
        and summary["total_logs"] == summary["logs_with_step_marker"]
        and summary["total_logs"] == summary["logs_with_command_targets"]
        and summary["total_logs"] == summary["logs_with_all_targets_passed"]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", action="append", required=True, help="Path to CI log file.")
    parser.add_argument(
        "--require-target",
        action="append",
        default=[],
        help="Required pytest target that must appear in command and pass output.",
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
    required_targets = (
        tuple(args.require_target) if args.require_target else tuple(DEFAULT_REQUIRED_TARGETS)
    )
    report = build_runtime_log_report(
        [Path(path) for path in args.log], required_targets=required_targets
    )

    if args.format == "comment":
        print(build_comment_report(report), end="")
    else:
        print(json.dumps(report, indent=2))

    return 0 if is_report_passing(report) else 1


if __name__ == "__main__":
    raise SystemExit(main())
