"""Excel template mapping utilities for itinerary exports."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

DEFAULT_TEMPLATE_VERSION = "ITIN-2025.1"


def _package_mapping_resource() -> resources.abc.Traversable | None:
    try:
        resource = resources.files("travel_plan_permission").joinpath(
            "config", "excel_mappings.yaml"
        )
    except ModuleNotFoundError:
        return None
    return resource if resource.is_file() else None


def _package_template_resource(template_file: str) -> resources.abc.Traversable | None:
    try:
        resource = resources.files("travel_plan_permission").joinpath("templates", template_file)
    except ModuleNotFoundError:
        return None
    return resource if resource.is_file() else None


def _default_mapping_path() -> Path | None:
    """Return the repository mapping file if present."""

    for parent in Path(__file__).resolve().parents:
        candidate = parent / "config" / "excel_mappings.yaml"
        if candidate.exists():
            return candidate
    return None


@dataclass(frozen=True)
class TemplateMapping:
    """Structured mapping for a single spreadsheet template."""

    version: str
    cells: dict[str, str]
    dropdowns: dict[str, dict[str, object]]
    checkboxes: dict[str, dict[str, str]]
    formulas: dict[str, dict[str, str]]
    metadata: dict[str, object]

    def missing_fields(self, required_fields: Iterable[str]) -> list[str]:
        """Return any required fields that lack a cell mapping."""

        return [field for field in required_fields if field not in self.cells]


def load_template_mapping(
    version: str = DEFAULT_TEMPLATE_VERSION,
    path: str | Path | None = None,
    *,
    allow_version_mismatch: bool = False,
) -> TemplateMapping:
    """Load a mapping for a specific template version.

    The loader enforces that the requested version is present and, by default,
    matches the version declared in the metadata block.
    """

    mapping_path = Path(path) if path is not None else _default_mapping_path()
    if mapping_path is None or not mapping_path.exists():
        resource = _package_mapping_resource()
        if resource is None:
            raise FileNotFoundError("Unable to locate excel_mappings.yaml")
        mapping_text = resource.read_text(encoding="utf-8")
    else:
        mapping_text = mapping_path.read_text(encoding="utf-8")

    data = yaml.safe_load(mapping_text) or {}
    templates: dict[str, dict[str, Any]] = data.get("templates") or {}

    if version not in templates:
        available = ", ".join(sorted(templates)) or "none"
        raise ValueError(f"Template version '{version}' not found; available versions: {available}")

    payload = templates[version]
    metadata = payload.get("metadata") or {}
    declared_version = metadata.get("template_id", version)
    if declared_version != version and not allow_version_mismatch:
        raise ValueError(
            f"Mapping metadata declares template_id '{declared_version}',"
            f" but '{version}' was requested."
        )
    template_file = metadata.get("template_file")
    if isinstance(template_file, str):
        for parent in Path(__file__).resolve().parents:
            candidate = parent / "templates" / template_file
            if candidate.exists():
                break
        else:
            if _package_template_resource(template_file) is None:
                raise FileNotFoundError(
                    f"Unable to locate templates/{template_file} for template version '{version}'"
                )

    cells = payload.get("cells") or {}
    dropdowns = payload.get("dropdowns") or {}
    checkboxes = payload.get("checkboxes") or {}
    formulas = payload.get("formulas") or {}

    return TemplateMapping(
        version=version,
        cells=dict(cells),
        dropdowns=dict(dropdowns),
        checkboxes=dict(checkboxes),
        formulas=dict(formulas),
        metadata=dict(metadata),
    )
