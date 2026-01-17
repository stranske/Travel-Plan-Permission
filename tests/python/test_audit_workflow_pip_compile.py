import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.audit_workflow_pip_compile import (
    PATTERNS,
    REPLACEMENT_COMMAND,
    find_occurrences,
    render_replacement_suggestions,
)


def test_find_occurrences_reports_matches(tmp_path: Path) -> None:
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    sample = workflows_dir / "ci.yml"
    sample.write_text(
        "\n".join(
            [
                "steps:",
                "  - run: pip-compile requirements.in",
                "  - run: uv pip compile pyproject.toml",
            ]
        ),
        encoding="utf-8",
    )

    pip_matches = find_occurrences(workflows_dir, PATTERNS["pip-compile"])
    uv_matches = find_occurrences(workflows_dir, PATTERNS["uv pip compile"])

    assert len(pip_matches) == 1
    assert "pip-compile" in pip_matches[0]
    assert len(uv_matches) == 1
    assert "uv pip compile" in uv_matches[0]


def test_find_occurrences_missing_directory() -> None:
    missing = Path("does-not-exist")
    assert find_occurrences(missing, PATTERNS["pip-compile"]) == []


def test_render_replacement_suggestions() -> None:
    matches = ["workflow.yml:12: pip-compile requirements.in"]
    suggestions = render_replacement_suggestions(matches)

    assert len(suggestions) == 1
    assert matches[0] in suggestions[0]
    assert REPLACEMENT_COMMAND in suggestions[0]
