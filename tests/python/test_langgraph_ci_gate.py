import ast
import shlex
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
GATE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pr-00-gate.yml"


def _workflow(path: Path) -> dict[str, object]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


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


def _module_has_prefer_langgraph_true(tree: ast.AST) -> bool:
    return _function_calls_prefer_langgraph_true(tree)


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


def _assert_targets_exercise_langgraph(
    *,
    command: str,
    repo_root: Path,
    workflow_name: str,
) -> None:
    targets = _extract_pytest_targets(command)
    assert targets, f"{workflow_name}: no pytest targets found"

    missing: list[str] = []
    for target in targets:
        target_parts = target.split("::")
        file_path = repo_root / target_parts[0]
        assert file_path.exists(), f"{workflow_name}: missing test target {target_parts[0]}"
        tree = ast.parse(file_path.read_text(encoding="utf-8"))

        if len(target_parts) == 1:
            if not _module_has_prefer_langgraph_true(tree):
                missing.append(target)
            continue

        scope_name = target_parts[-1]
        scope = _find_named_scope(tree, scope_name)
        if scope is None:
            missing.append(target)
            continue
        if not _function_calls_prefer_langgraph_true(scope):
            missing.append(target)

    assert not missing, (
        f"{workflow_name}: pytest targets must exercise prefer_langgraph=True path; "
        f"offending targets: {', '.join(missing)}"
    )


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
    _assert_targets_exercise_langgraph(
        command=test_command,
        repo_root=REPO_ROOT,
        workflow_name="ci.yml orchestration job",
    )


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
    _assert_targets_exercise_langgraph(
        command=test_command,
        repo_root=REPO_ROOT,
        workflow_name="pr-00-gate.yml orchestration-tests job",
    )


def test_langgraph_target_validator_rejects_fallback_only_targets(tmp_path: Path) -> None:
    test_file = tmp_path / "test_fallback_only.py"
    test_file.write_text(
        "\n".join(
            [
                "from travel_plan_permission.orchestration import run_policy_graph",
                "",
                "",
                "def test_fallback_only():",
                "    run_policy_graph(None, prefer_langgraph=False)",
                "",
            ]
        ),
        encoding="utf-8",
    )
    command = "pytest test_fallback_only.py::test_fallback_only -v"

    with pytest.raises(AssertionError, match="must exercise prefer_langgraph=True path"):
        _assert_targets_exercise_langgraph(
            command=command,
            repo_root=tmp_path,
            workflow_name="synthetic-workflow",
        )
