import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.audit_langgraph_workflow_tests import (  # noqa: E402
    build_comment_report,
    build_runtime_report,
    collect_langgraph_runtime_targets,
)


def test_collect_langgraph_runtime_targets_reads_step_targets(tmp_path: Path) -> None:
    workflow = tmp_path / "ci.yml"
    workflow.write_text(
        "\n".join(
            [
                "name: CI",
                "jobs:",
                "  orchestration:",
                "    name: LangGraph Orchestration CI",
                "    runs-on: ubuntu-latest",
                "    steps:",
                "      - name: Run LangGraph orchestration tests",
                "        run: |",
                "          pytest tests/test_langgraph.py::test_prefers_langgraph -v",
            ]
        ),
        encoding="utf-8",
    )
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    test_file = tests_dir / "test_langgraph.py"
    test_file.write_text(
        "\n".join(
            [
                "def test_prefers_langgraph():",
                "    run_policy_graph(plan, prefer_langgraph=True)",
            ]
        ),
        encoding="utf-8",
    )

    targets = collect_langgraph_runtime_targets([workflow], repo_root=tmp_path)

    assert len(targets) == 1
    target = targets[0]
    assert target.workflow == workflow.as_posix()
    assert target.job_id == "orchestration"
    assert target.target == "tests/test_langgraph.py::test_prefers_langgraph"
    assert target.file_exists is True
    assert target.prefer_langgraph_true is True


def test_build_runtime_report_marks_missing_and_non_langgraph_targets(tmp_path: Path) -> None:
    workflow = tmp_path / "ci.yml"
    workflow.write_text(
        "\n".join(
            [
                "name: CI",
                "jobs:",
                "  orchestration:",
                "    runs-on: ubuntu-latest",
                "    steps:",
                "      - name: Run LangGraph orchestration tests",
                "        run: |",
                "          pytest tests/exists.py::test_without_langgraph tests/missing.py -v",
            ]
        ),
        encoding="utf-8",
    )
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "exists.py").write_text(
        "\n".join(
            [
                "def test_without_langgraph():",
                "    run_policy_graph(plan, prefer_langgraph=False)",
            ]
        ),
        encoding="utf-8",
    )

    report = build_runtime_report([workflow], repo_root=tmp_path)

    assert report["summary"] == {
        "total_targets": 2,
        "existing_targets": 1,
        "prefer_langgraph_targets": 0,
    }
    targets = {entry["target"]: entry for entry in report["results"]}
    assert targets["tests/exists.py::test_without_langgraph"]["file_exists"] is True
    assert targets["tests/exists.py::test_without_langgraph"]["prefer_langgraph_true"] is False
    assert targets["tests/missing.py"]["file_exists"] is False


def test_build_comment_report_formats_table(tmp_path: Path) -> None:
    report = {
        "workflows": [".github/workflows/ci.yml"],
        "summary": {
            "total_targets": 1,
            "existing_targets": 1,
            "prefer_langgraph_targets": 1,
        },
        "results": [
            {
                "workflow": ".github/workflows/ci.yml",
                "job_id": "orchestration",
                "job_name": "LangGraph Orchestration CI",
                "target": "tests/python/test_orchestration_smoke.py::test_policy_graph_langgraph_smoke",
                "target_file": "tests/python/test_orchestration_smoke.py",
                "scope": "test_policy_graph_langgraph_smoke",
                "file_exists": True,
                "prefer_langgraph_true": True,
            }
        ],
    }

    comment = build_comment_report(report)

    assert "LangGraph Runtime Test Target Audit" in comment
    assert (
        "| Workflow | Job | Pytest target | File exists | `prefer_langgraph=True` path |" in comment
    )
    assert (
        "`tests/python/test_orchestration_smoke.py::test_policy_graph_langgraph_smoke`" in comment
    )
    assert "| YES | YES |" in comment


def test_real_ci_workflows_include_langgraph_targets() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    workflows = [
        repo_root / ".github" / "workflows" / "ci.yml",
        repo_root / ".github" / "workflows" / "pr-00-gate.yml",
    ]
    # Sanity-guard the test assumption that the workflow files are parseable YAML.
    for workflow in workflows:
        yaml.safe_load(workflow.read_text(encoding="utf-8"))

    report = build_runtime_report(workflows, repo_root=repo_root)

    assert report["summary"]["total_targets"] >= 4
    assert report["summary"]["existing_targets"] == report["summary"]["total_targets"]
    assert report["summary"]["prefer_langgraph_targets"] == report["summary"]["total_targets"]
