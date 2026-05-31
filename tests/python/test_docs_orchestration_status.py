from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "docs" / "ORCHESTRATION_PLAN.md"


def test_plan_marks_agents_unimplemented() -> None:
    content = PLAN.read_text(encoding="utf-8")

    assert "## Implementation Status" in content
    assert "`future.llm_agents` | LLM agents | `STATUS:NOT_IMPLEMENTED`" in content
    assert (
        "`future.vendor_search` | Vendor/travel-provider search | `STATUS:NOT_IMPLEMENTED`"
        in content
    )
    assert (
        "`future.privacy_boundary` | Future privacy boundary for LLM processing "
        "| `STATUS:NOT_IMPLEMENTED`" in content
    )
    assert "LLM agents are implemented as node functions" not in content


def test_plan_lists_built_deterministic_nodes_and_no_openai_client_code() -> None:
    content = PLAN.read_text(encoding="utf-8")

    for built_capability in (
        "`deterministic.policy_check_node`",
        "`deterministic.planner_runtime_node`",
        "`deterministic.spreadsheet_node`",
    ):
        assert f"{built_capability} |" in content
        assert "`STATUS:BUILT`" in content

    for node_name in ("policy_check", "planner_runtime", "spreadsheet"):
        assert node_name in content

    result = subprocess.run(
        ["rg", "-n", r"ChatOpenAI|langchain_openai|import openai", "src/"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1, result.stdout
