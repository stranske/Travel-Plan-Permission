from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

import pytest


def _assert_yaml_pair_matches(repo_default: Traversable, packaged_default: Traversable) -> None:
    assert (
        repo_default.read_bytes() == packaged_default.read_bytes()
    ), f"Default YAML mismatch: {repo_default} != {packaged_default}"


@pytest.mark.parametrize(
    "filename",
    [
        "policy.yaml",
        "validation.yaml",
        "providers.yaml",
        "approval_rules.yaml",
        "excel_mappings.yaml",
    ],
)
def test_packaged_yaml_matches_repo_defaults(filename: str) -> None:
    repo_default = Path(__file__).resolve().parents[2] / "config" / filename
    packaged_default = resources.files("travel_plan_permission").joinpath("config", filename)
    _assert_yaml_pair_matches(repo_default, packaged_default)


@pytest.mark.parametrize("changed_copy", ["repo", "package"])
def test_config_parity_guard_detects_one_sided_change(tmp_path: Path, changed_copy: str) -> None:
    repo_default = tmp_path / "repo" / "policy.yaml"
    packaged_default = tmp_path / "package" / "policy.yaml"
    for path in (repo_default, packaged_default):
        path.parent.mkdir()
        path.write_bytes(b"rules: []\n")
    _assert_yaml_pair_matches(repo_default, packaged_default)

    # Even a comment-only edit must be synchronized: this is byte parity.
    (tmp_path / changed_copy / "policy.yaml").write_bytes(b"rules: []\n# changed\n")
    with pytest.raises(AssertionError, match="Default YAML mismatch") as error:
        _assert_yaml_pair_matches(repo_default, packaged_default)
    assert str(repo_default) in str(error.value)
    assert str(packaged_default) in str(error.value)


def test_mapping_resource_exists() -> None:
    mapping = resources.files("travel_plan_permission").joinpath("config", "excel_mappings.yaml")
    assert mapping.is_file()
    assert "templates" in mapping.read_text(encoding="utf-8")


def test_approval_rules_resource_exists() -> None:
    rules = resources.files("travel_plan_permission").joinpath("config", "approval_rules.yaml")
    assert rules.is_file()
    assert "default_under_100" in rules.read_text(encoding="utf-8")


def test_template_resource_exists() -> None:
    template = resources.files("travel_plan_permission").joinpath(
        "templates", "Travel_Itinerary_Form_Jan_1_2026_runtime.xlsx"
    )
    assert template.is_file()
    assert template.read_bytes().startswith(b"PK")


def test_portal_template_resources_exist() -> None:
    templates = resources.files("travel_plan_permission").joinpath("templates")
    home = templates.joinpath("portal_home.html")
    expense = templates.joinpath("portal_expense.html")
    draft_entry = templates.joinpath("draft_entry.html")
    queue = templates.joinpath("manager_review_queue.html")
    detail = templates.joinpath("manager_review_detail.html")

    assert home.is_file()
    assert "Travel Request Portal" in home.read_text(encoding="utf-8")
    assert expense.is_file()
    assert "Prepare an expense report from an approved request." in expense.read_text(
        encoding="utf-8"
    )
    assert draft_entry.is_file()
    assert "Travel Request Draft Entry" in draft_entry.read_text(encoding="utf-8")
    assert queue.is_file()
    assert "Manager review queue" in queue.read_text(encoding="utf-8")
    assert detail.is_file()
    assert "Manager review detail" in detail.read_text(encoding="utf-8")
