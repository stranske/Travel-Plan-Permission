import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.validate_dependency_refresh_workflow import (
    EXPECTED_COMPILE_COMMAND,
    find_workflow_issues,
)


def test_find_workflow_issues_reports_expected_problems() -> None:
    content = "\n".join(
        [
            "steps:",
            "  - run: pip-compile requirements.in",
            "  - run: pip-compile --extra=dev --output-file=requirements-dev.lock pyproject.toml",
        ]
    )

    issues = find_workflow_issues(content)

    assert "Found pip-compile usage; expected uv pip compile." in issues
    assert "Found requirements-dev.lock usage; expected single requirements.lock." in issues
    assert "Expected uv pip compile command with extras is missing." in issues
    assert (
        "Expected verification subprocess.run for uv pip compile with extras is missing." in issues
    )


def test_find_workflow_issues_accepts_expected_command() -> None:
    content = "\n".join(
        [
            "steps:",
            f"  - run: {EXPECTED_COMPILE_COMMAND}",
            "  - run: |",
            "      python - <<'PY'",
            "      import subprocess",
            "      compiled_proc = subprocess.run(['uv', 'pip', 'compile', 'pyproject.toml',",
            "                                     '--extra', 'dev', '--extra', 'ocr',",
            "                                     '--extra', 'orchestration'])",
            "      PY",
            "  - run: uv pip sync requirements.lock",
        ]
    )

    assert find_workflow_issues(content) == []
