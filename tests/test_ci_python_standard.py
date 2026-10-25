"""Keep repository-owned CI callers on the owner's tested Python standard."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
RUNTIME_KEYS = {
    "python-version",
    "python-versions",
    "primary-python-version",
    "coverage-python-version",
    "PYTHON_VERSION",
    "COVERAGE_REFERENCE_RUNTIME",
}


def _runtime_pins(node: Any, location: str) -> Iterator[tuple[str, Any]]:
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{location}.{key}"
            if key in RUNTIME_KEYS:
                yield path, value
            yield from _runtime_pins(value, path)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _runtime_pins(value, f"{location}[{index}]")


def _contains_old_runtime(value: Any) -> bool:
    if isinstance(value, list):
        return any(_contains_old_runtime(item) for item in value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            pass
        else:
            if decoded != value:
                return _contains_old_runtime(decoded)
    return str(value) == "3.12" or str(value).startswith("3.12.")


def test_workflow_python_pins_follow_standard() -> None:
    workflows = {
        path.name: yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in sorted(WORKFLOWS.iterdir())
        if path.is_file() and path.suffix in {".yml", ".yaml"}
    }
    assert workflows, "No workflow YAML was inspected"
    offenders = [
        location
        for filename, workflow in workflows.items()
        for location, value in _runtime_pins(workflow, filename)
        if _contains_old_runtime(value)
    ]
    assert not offenders, f"Python 3.12 runtime pins remain: {offenders}"
    for filename, job in (("ci.yml", "python"), ("pr-00-gate.yml", "python-ci")):
        config = workflows[filename]["jobs"][job]
        assert json.loads(config["with"]["python-versions"]) == ["3.13", "3.14"]
        assert config["with"]["primary-python-version"] == "3.14"
        assert not config.get("continue-on-error", False)

    integration_steps = workflows["portal-postgres-integration.yml"]["jobs"][
        "postgres-integration"
    ]["steps"]
    runtimes = [
        step["with"]["python-version"]
        for step in integration_steps
        if "python-version" in step.get("with", {})
    ]
    assert runtimes == ["3.14"]


class _UniqueKeyLoader(yaml.SafeLoader):
    """Reject duplicate explicit keys while retaining SafeLoader semantics."""

    def construct_mapping(self, node: Any, deep: bool = False) -> dict[Any, Any]:
        seen = set()
        for key_node, _ in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                continue
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"duplicate key {key!r}",
                    key_node.start_mark,
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def test_workflow_yaml_has_no_duplicate_keys() -> None:
    for path in sorted(WORKFLOWS.iterdir()):
        if path.is_file() and path.suffix in {".yml", ".yaml"}:
            yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)


def test_duplicate_key_validation_rejects_hidden_runtime_pin() -> None:
    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "ci_python_standard"
        / "duplicate-runtime.yml"
    )
    with pytest.raises(
        yaml.constructor.ConstructorError, match="duplicate key 'python-version'"
    ):
        yaml.load(fixture.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)


def test_duplicate_key_validation_allows_explicit_merge_overrides() -> None:
    document = (
        "base: &base {python-version: '3.13'}\njob: {<<: *base, python-version: '3.14'}"
    )
    loaded = yaml.load(document, Loader=_UniqueKeyLoader)
    assert loaded["job"]["python-version"] == "3.14"
