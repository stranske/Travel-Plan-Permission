from pathlib import Path

import yaml

from travel_plan_permission.mapping import (
    DEFAULT_TEMPLATE_VERSION,
    load_template_mapping,
)
from travel_plan_permission.prompt_flow import CANONICAL_TRIP_FIELDS


def test_mapping_covers_canonical_fields():
    mapping = load_template_mapping()

    missing = mapping.missing_fields(CANONICAL_TRIP_FIELDS)
    assert missing == []
    assert mapping.metadata.get("template_id") == DEFAULT_TEMPLATE_VERSION


def test_version_mismatch_requires_opt_in(tmp_path: Path):
    source = Path("config/excel_mappings.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(source)
    data["templates"][DEFAULT_TEMPLATE_VERSION]["metadata"]["template_id"] = (
        "ITIN-2025.2"
    )
    target = tmp_path / "excel_mappings.yaml"
    target.write_text(yaml.safe_dump(data), encoding="utf-8")

    # Default behavior rejects mismatched version declarations
    try:
        load_template_mapping(path=target)
    except ValueError as exc:  # noqa: PERF203
        assert "template_id" in str(exc)
    else:
        raise AssertionError("Expected ValueError for mismatched template_id")

    # Allowing mismatches lets the mapping load for review flows
    mapping = load_template_mapping(path=target, allow_version_mismatch=True)
    assert mapping.version == DEFAULT_TEMPLATE_VERSION
