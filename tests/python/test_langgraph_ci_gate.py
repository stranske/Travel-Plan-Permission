from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
GATE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pr-00-gate.yml"


def _assert_langgraph_orchestration_job(workflow_path: Path) -> None:
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    orchestration_job = workflow["jobs"]["orchestration-tests"]

    assert orchestration_job["name"] == "Orchestration Tests (LangGraph)"

    step_by_name = {step["name"]: step for step in orchestration_job["steps"]}
    install_command = step_by_name["Install dependencies with orchestration extra"]["run"]
    assert 'pip install -e ".[orchestration,dev]"' in install_command

    test_command = step_by_name["Run LangGraph orchestration tests"]["run"]
    assert "tests/orchestration_graph_test.py" in test_command
    assert "tests/python/test_langgraph_orchestration.py" in test_command


def test_ci_runs_langgraph_path_with_orchestration_extra() -> None:
    _assert_langgraph_orchestration_job(CI_WORKFLOW)


def test_gate_runs_langgraph_path_with_orchestration_extra() -> None:
    _assert_langgraph_orchestration_job(GATE_WORKFLOW)
