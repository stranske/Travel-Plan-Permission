from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
GATE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pr-00-gate.yml"


def _workflow(path: Path) -> dict[str, object]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_ci_runs_langgraph_path_with_orchestration_extra() -> None:
    workflow = _workflow(CI_WORKFLOW)
    orchestration_job = workflow["jobs"]["orchestration"]

    assert orchestration_job["name"] == "LangGraph Orchestration CI"

    step_by_name = {step["name"]: step for step in orchestration_job["steps"]}
    install_command = step_by_name["Install dependencies with orchestration extra"]["run"]
    assert 'pip install -e ".[orchestration,dev]"' in install_command

    test_command = step_by_name["Run LangGraph orchestration tests"]["run"]
    assert "tests/orchestration_graph_test.py" in test_command
    assert "tests/python/test_langgraph_orchestration.py" in test_command
    assert "test_policy_graph_langgraph_smoke" in test_command
    assert "test_policy_graph_prefers_langgraph_when_available" in test_command


def test_gate_runs_langgraph_path_with_orchestration_extra() -> None:
    workflow = _workflow(GATE_WORKFLOW)
    orchestration_job = workflow["jobs"]["orchestration-tests"]

    assert orchestration_job["name"] == "Orchestration Tests (LangGraph)"

    step_by_name = {step["name"]: step for step in orchestration_job["steps"]}
    install_command = step_by_name["Install dependencies with orchestration extra"]["run"]
    assert 'pip install -e ".[orchestration,dev]"' in install_command

    test_command = step_by_name["Run LangGraph orchestration tests"]["run"]
    assert "tests/orchestration_graph_test.py" in test_command
    assert "tests/python/test_langgraph_orchestration.py" in test_command
