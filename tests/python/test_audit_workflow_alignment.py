import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.audit_workflow_alignment import collect_workflow_files, compare_workflow_trees


def test_collect_workflow_files_missing_directory(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(FileNotFoundError):
        collect_workflow_files(missing)


def test_compare_workflow_trees_reports_differences(tmp_path: Path) -> None:
    local = tmp_path / "local"
    workflows = tmp_path / "workflows"
    local.mkdir()
    workflows.mkdir()

    (local / "shared.yml").write_text("local", encoding="utf-8")
    (workflows / "shared.yml").write_text("workflows", encoding="utf-8")
    (local / "local-only.yml").write_text("local", encoding="utf-8")
    (workflows / "workflows-only.yml").write_text("workflows", encoding="utf-8")

    missing, extra, modified = compare_workflow_trees(local, workflows)

    assert missing == ["workflows-only.yml"]
    assert extra == ["local-only.yml"]
    assert modified == ["shared.yml"]
