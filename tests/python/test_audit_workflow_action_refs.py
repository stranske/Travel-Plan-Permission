import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.audit_workflow_action_refs import (  # noqa: E402
    build_comment_report,
    build_validation_report,
    collect_action_references,
    validate_action_reference,
)


def test_collect_action_references_ignores_local_and_docker_refs(tmp_path: Path) -> None:
    workflow = tmp_path / "ci.yml"
    workflow.write_text(
        "\n".join(
            [
                "name: CI",
                "jobs:",
                "  build:",
                "    runs-on: ubuntu-latest",
                "    steps:",
                "      - uses: actions/checkout@v4",
                "      - uses: ./.github/actions/setup",
                "      - uses: docker://alpine:3.20",
                "      - uses: actions/setup-python@v5",
            ]
        ),
        encoding="utf-8",
    )

    refs = collect_action_references([workflow])

    assert refs == {
        "actions/checkout@v4": (workflow.as_posix(),),
        "actions/setup-python@v5": (workflow.as_posix(),),
    }


def test_validate_action_reference_accepts_tag_reference() -> None:
    statuses = {
        "https://api.github.com/repos/actions/checkout": 200,
        "https://github.com/marketplace/actions/checkout": 200,
        "https://api.github.com/repos/actions/checkout/git/ref/tags/v4": 200,
    }

    result = validate_action_reference(
        "actions/checkout@v4",
        (".github/workflows/ci.yml",),
        fetch_status=lambda url: statuses.get(url, 404),
    )

    assert result.repository_ok is True
    assert result.marketplace_ok is True
    assert result.version_ok is True
    assert result.is_valid is True


def test_validate_action_reference_falls_back_to_branch() -> None:
    statuses = {
        "https://api.github.com/repos/org/example-action": 200,
        "https://github.com/marketplace/actions/example-action": 200,
        "https://api.github.com/repos/org/example-action/git/ref/tags/main": 404,
        "https://api.github.com/repos/org/example-action/branches/main": 200,
    }

    result = validate_action_reference(
        "org/example-action@main",
        (".github/workflows/ci.yml",),
        fetch_status=lambda url: statuses.get(url, 404),
    )

    assert result.version_ok is True
    assert result.version_url.endswith("/branches/main")
    assert result.is_valid is True


def test_build_validation_report_and_comment_format(tmp_path: Path) -> None:
    workflow = tmp_path / "ci.yml"
    workflow.write_text(
        "\n".join(
            [
                "name: CI",
                "jobs:",
                "  build:",
                "    runs-on: ubuntu-latest",
                "    steps:",
                "      - uses: actions/checkout@v4",
            ]
        ),
        encoding="utf-8",
    )

    statuses = {
        "https://api.github.com/repos/actions/checkout": 200,
        "https://github.com/marketplace/actions/checkout": 200,
        "https://api.github.com/repos/actions/checkout/git/ref/tags/v4": 200,
    }

    report = build_validation_report([workflow], fetch_status=lambda url: statuses.get(url, 404))

    assert report["summary"]["total_references"] == 1
    assert report["summary"]["invalid_references"] == 0
    assert report["summary"]["unknown_references"] == 0

    comment = build_comment_report(report)
    assert "GitHub Action Reference Validation" in comment
    assert "`actions/checkout@v4`" in comment
    assert (
        "| Action reference | Workflow files | Repository | Marketplace | Version ref | Result |"
        in comment
    )


def test_build_comment_report_includes_needs_human_for_invalid_refs() -> None:
    report = {
        "generated_at_utc": "2026-04-26T00:00:00+00:00",
        "workflows": [".github/workflows/ci.yml"],
        "summary": {
            "total_references": 1,
            "valid_references": 0,
            "invalid_references": 1,
            "unknown_references": 0,
        },
        "results": [
            {
                "reference": "actions/checkout@v4",
                "workflows": [".github/workflows/ci.yml"],
                "repository_status": 200,
                "marketplace_status": 404,
                "version_status": 200,
                "repository_ok": True,
                "marketplace_ok": False,
                "version_ok": True,
                "valid": False,
                "classification": "invalid",
            }
        ],
    }

    comment = build_comment_report(report)

    assert "Needs human" in comment
    assert "REVIEW" in comment


def test_build_validation_report_marks_unverified_when_offline(tmp_path: Path) -> None:
    workflow = tmp_path / "ci.yml"
    workflow.write_text(
        "\n".join(
            [
                "name: CI",
                "jobs:",
                "  build:",
                "    runs-on: ubuntu-latest",
                "    steps:",
                "      - uses: actions/checkout@v4",
            ]
        ),
        encoding="utf-8",
    )

    report = build_validation_report([workflow], fetch_status=lambda _: 0)

    assert report["summary"]["valid_references"] == 0
    assert report["summary"]["invalid_references"] == 0
    assert report["summary"]["unknown_references"] == 1
    assert report["results"][0]["classification"] == "unknown"


def test_validate_action_reference_rejects_invalid_reference() -> None:
    with pytest.raises(ValueError, match="Invalid action reference format"):
        validate_action_reference(
            "./.github/actions/local",
            (".github/workflows/ci.yml",),
            fetch_status=lambda _: 200,
        )
