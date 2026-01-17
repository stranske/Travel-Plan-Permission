import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.audit_workflow_alignment import (
    build_workflow_report,
    build_markdown_report,
    collect_workflow_files,
    compare_workflow_trees,
    write_json_report,
)


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


def test_build_workflow_report_and_write_json(tmp_path: Path) -> None:
    local = tmp_path / "local"
    workflows = tmp_path / "workflows"
    local.mkdir()
    workflows.mkdir()

    (local / "shared.yml").write_text("local", encoding="utf-8")
    (workflows / "shared.yml").write_text("workflows", encoding="utf-8")
    (workflows / "workflows-only.yml").write_text("workflows", encoding="utf-8")

    report = build_workflow_report(local, workflows)

    assert report["missing"] == ["workflows-only.yml"]
    assert report["extra"] == []
    assert report["modified"] == ["shared.yml"]
    assert report["summary"] == {"missing": 1, "extra": 0, "modified": 1}

    output_path = tmp_path / "report.json"
    write_json_report(report, output_path)
    content = output_path.read_text(encoding="utf-8")
    assert '"missing": [' in content


def test_build_markdown_report_includes_needs_human(tmp_path: Path) -> None:
    local = tmp_path / "local"
    workflows = tmp_path / "workflows"
    local.mkdir()
    workflows.mkdir()

    (local / "shared.yml").write_text("local", encoding="utf-8")
    (workflows / "shared.yml").write_text("workflows", encoding="utf-8")

    report = build_workflow_report(local, workflows)
    markdown = build_markdown_report(report)

    assert "Workflow alignment report" in markdown
    assert "Needs human" in markdown
