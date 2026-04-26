import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.audit_langgraph_ci_runtime_logs import (  # noqa: E402
    DEFAULT_REQUIRED_TARGETS,
    build_comment_report,
    build_runtime_log_report,
    is_report_passing,
)


def test_build_runtime_log_report_marks_log_with_complete_langgraph_evidence(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "run.log"
    log_path.write_text(
        "\n".join(
            [
                "2026-04-20T08:11:31Z ##[group]Run LangGraph orchestration tests",
                (
                    "2026-04-20T08:11:32Z pytest tests/orchestration_graph_test.py "
                    "tests/python/test_langgraph_orchestration.py "
                    "tests/python/test_orchestration_smoke.py::test_policy_graph_langgraph_smoke "
                    "tests/python/test_orchestration_smoke.py::"
                    "test_policy_graph_prefers_langgraph_when_available -v"
                ),
                "2026-04-20T08:11:50Z tests/orchestration_graph_test.py PASSED",
                "2026-04-20T08:11:51Z tests/python/test_langgraph_orchestration.py PASSED",
                (
                    "2026-04-20T08:11:53Z "
                    "tests/python/test_orchestration_smoke.py::test_policy_graph_langgraph_smoke "
                    "PASSED"
                ),
                (
                    "2026-04-20T08:11:54Z "
                    "tests/python/test_orchestration_smoke.py::"
                    "test_policy_graph_prefers_langgraph_when_available PASSED"
                ),
            ]
        ),
        encoding="utf-8",
    )

    report = build_runtime_log_report([log_path], required_targets=DEFAULT_REQUIRED_TARGETS)

    assert report["summary"] == {
        "total_logs": 1,
        "logs_with_step_marker": 1,
        "logs_with_command_targets": 1,
        "logs_with_all_targets_passed": 1,
    }
    assert is_report_passing(report) is True


def test_build_runtime_log_report_accepts_multiline_github_command_and_file_target(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "github-run.log"
    log_path.write_text(
        "\n".join(
            [
                "LangGraph Orchestration CI\tRun LangGraph orchestration tests\t##[group]Run pytest \\",
                "LangGraph Orchestration CI\tRun LangGraph orchestration tests\t\x1b[36;1mpytest \\ \x1b[0m",
                (
                    "LangGraph Orchestration CI\tRun LangGraph orchestration tests\t"
                    "\x1b[36;1m  tests/orchestration_graph_test.py \\ \x1b[0m"
                ),
                (
                    "LangGraph Orchestration CI\tRun LangGraph orchestration tests\t"
                    "\x1b[36;1m  tests/python/test_langgraph_orchestration.py \\ \x1b[0m"
                ),
                (
                    "LangGraph Orchestration CI\tRun LangGraph orchestration tests\t"
                    "\x1b[36;1m  tests/python/test_orchestration_smoke.py::"
                    "test_policy_graph_langgraph_smoke \\ \x1b[0m"
                ),
                (
                    "LangGraph Orchestration CI\tRun LangGraph orchestration tests\t"
                    "\x1b[36;1m  tests/python/test_orchestration_smoke.py::"
                    "test_policy_graph_prefers_langgraph_when_available -v\x1b[0m"
                ),
                "LangGraph Orchestration CI\tRun LangGraph orchestration tests\tshell: /usr/bin/bash -e {0}",
                (
                    "LangGraph Orchestration CI\tRun LangGraph orchestration tests\t"
                    "tests/orchestration_graph_test.py::"
                    "test_langgraph_compiled_path_creates_spreadsheet PASSED [ 25%]"
                ),
                (
                    "LangGraph Orchestration CI\tRun LangGraph orchestration tests\t"
                    "tests/python/test_langgraph_orchestration.py::"
                    "test_policy_graph_runs_with_langgraph PASSED [ 50%]"
                ),
                (
                    "LangGraph Orchestration CI\tRun LangGraph orchestration tests\t"
                    "tests/python/test_orchestration_smoke.py::"
                    "test_policy_graph_langgraph_smoke PASSED [ 75%]"
                ),
                (
                    "LangGraph Orchestration CI\tRun LangGraph orchestration tests\t"
                    "tests/python/test_orchestration_smoke.py::"
                    "test_policy_graph_prefers_langgraph_when_available PASSED [100%]"
                ),
            ]
        ),
        encoding="utf-8",
    )

    report = build_runtime_log_report([log_path], required_targets=DEFAULT_REQUIRED_TARGETS)

    assert report["summary"] == {
        "total_logs": 1,
        "logs_with_step_marker": 1,
        "logs_with_command_targets": 1,
        "logs_with_all_targets_passed": 1,
    }
    assert is_report_passing(report) is True


def test_build_runtime_log_report_accepts_unknown_step_job_label(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "unknown-step-run.log"
    log_path.write_text(
        "\n".join(
            [
                "LangGraph Orchestration CI\tUNKNOWN STEP\t2026-04-26T21:26:02Z ##[group]Run pytest \\",
                "LangGraph Orchestration CI\tUNKNOWN STEP\t2026-04-26T21:26:02Z pytest \\",
                (
                    "LangGraph Orchestration CI\tUNKNOWN STEP\t2026-04-26T21:26:02Z "
                    "tests/orchestration_graph_test.py \\"
                ),
                (
                    "LangGraph Orchestration CI\tUNKNOWN STEP\t2026-04-26T21:26:02Z "
                    "tests/python/test_langgraph_orchestration.py \\"
                ),
                (
                    "LangGraph Orchestration CI\tUNKNOWN STEP\t2026-04-26T21:26:02Z "
                    "tests/python/test_orchestration_smoke.py::test_policy_graph_langgraph_smoke \\"
                ),
                (
                    "LangGraph Orchestration CI\tUNKNOWN STEP\t2026-04-26T21:26:02Z "
                    "tests/python/test_orchestration_smoke.py::"
                    "test_policy_graph_prefers_langgraph_when_available -v"
                ),
                (
                    "LangGraph Orchestration CI\tUNKNOWN STEP\t2026-04-26T21:26:06Z "
                    "tests/orchestration_graph_test.py::"
                    "test_langgraph_compiled_path_creates_spreadsheet PASSED [ 25%]"
                ),
                (
                    "LangGraph Orchestration CI\tUNKNOWN STEP\t2026-04-26T21:26:06Z "
                    "tests/python/test_langgraph_orchestration.py::"
                    "test_policy_graph_runs_with_langgraph PASSED [ 50%]"
                ),
                (
                    "LangGraph Orchestration CI\tUNKNOWN STEP\t2026-04-26T21:26:06Z "
                    "tests/python/test_orchestration_smoke.py::"
                    "test_policy_graph_langgraph_smoke PASSED [ 75%]"
                ),
                (
                    "LangGraph Orchestration CI\tUNKNOWN STEP\t2026-04-26T21:26:06Z "
                    "tests/python/test_orchestration_smoke.py::"
                    "test_policy_graph_prefers_langgraph_when_available PASSED [100%]"
                ),
            ]
        ),
        encoding="utf-8",
    )

    report = build_runtime_log_report([log_path], required_targets=DEFAULT_REQUIRED_TARGETS)

    assert report["summary"]["logs_with_step_marker"] == 1
    assert is_report_passing(report) is True


def test_build_runtime_log_report_detects_missing_pass_target(tmp_path: Path) -> None:
    log_path = tmp_path / "run.log"
    log_path.write_text(
        "\n".join(
            [
                "##[group]Run LangGraph orchestration tests",
                (
                    "pytest tests/orchestration_graph_test.py "
                    "tests/python/test_langgraph_orchestration.py "
                    "tests/python/test_orchestration_smoke.py::test_policy_graph_langgraph_smoke "
                    "tests/python/test_orchestration_smoke.py::"
                    "test_policy_graph_prefers_langgraph_when_available -v"
                ),
                "tests/orchestration_graph_test.py PASSED",
                "tests/python/test_langgraph_orchestration.py PASSED",
                (
                    "tests/python/test_orchestration_smoke.py::test_policy_graph_langgraph_smoke "
                    "PASSED"
                ),
            ]
        ),
        encoding="utf-8",
    )

    report = build_runtime_log_report([log_path], required_targets=DEFAULT_REQUIRED_TARGETS)

    assert report["summary"]["logs_with_all_targets_passed"] == 0
    assert report["results"][0]["missing_pass_targets"] == [
        "tests/python/test_orchestration_smoke.py::test_policy_graph_prefers_langgraph_when_available"
    ]
    assert is_report_passing(report) is False


def test_build_comment_report_surfaces_evidence_and_missing_targets(tmp_path: Path) -> None:
    good_log = tmp_path / "good.log"
    bad_log = tmp_path / "bad.log"
    good_log.write_text(
        "\n".join(
            [
                "##[group]Run LangGraph orchestration tests",
                (
                    "pytest tests/orchestration_graph_test.py "
                    "tests/python/test_langgraph_orchestration.py "
                    "tests/python/test_orchestration_smoke.py::test_policy_graph_langgraph_smoke "
                    "tests/python/test_orchestration_smoke.py::"
                    "test_policy_graph_prefers_langgraph_when_available -v"
                ),
                "tests/orchestration_graph_test.py PASSED",
                "tests/python/test_langgraph_orchestration.py PASSED",
                (
                    "tests/python/test_orchestration_smoke.py::test_policy_graph_langgraph_smoke "
                    "PASSED"
                ),
                (
                    "tests/python/test_orchestration_smoke.py::"
                    "test_policy_graph_prefers_langgraph_when_available PASSED"
                ),
            ]
        ),
        encoding="utf-8",
    )
    bad_log.write_text(
        "\n".join(
            [
                "pytest tests/orchestration_graph_test.py -v",
                "tests/orchestration_graph_test.py PASSED",
            ]
        ),
        encoding="utf-8",
    )

    report = build_runtime_log_report(
        [good_log, bad_log],
        required_targets=DEFAULT_REQUIRED_TARGETS,
    )
    comment = build_comment_report(report)

    assert "LangGraph CI Runtime Log Audit" in comment
    assert f"`{good_log.as_posix()}`" in comment
    assert f"`{bad_log.as_posix()}`" in comment
    assert "Step evidence:" in comment
    assert "Missing command targets:" in comment
