from pathlib import Path

import pytest
import yaml
from openpyxl import load_workbook
from openpyxl.utils.cell import coordinate_from_string

from travel_plan_permission import policy_api
from travel_plan_permission.mapping import (
    DEFAULT_TEMPLATE_VERSION,
    load_template_mapping,
)


def test_template_asset_loads_and_matches_mapping() -> None:
    mapping = load_template_mapping()
    template_file = mapping.metadata.get("template_file")
    assert template_file

    template_path = policy_api._default_template_path()
    assert template_path.parent.name == "templates"
    assert template_path.name == template_file

    workbook = load_workbook(template_path)
    sheet = workbook.active

    for cell_ref in mapping.cells.values():
        coordinate_from_string(cell_ref)
        assert sheet[cell_ref].value not in (None, "")

    for formula_config in mapping.formulas.values():
        cell_ref = formula_config.get("cell")
        formula = formula_config.get("formula")
        assert isinstance(cell_ref, str)
        assert isinstance(formula, str)
        assert sheet[cell_ref].value == formula


def test_template_mapping_requires_template_asset(tmp_path: Path) -> None:
    source = Path("config/excel_mappings.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(source)
    data["templates"][DEFAULT_TEMPLATE_VERSION]["metadata"][
        "template_file"
    ] = "missing_template.xlsx"
    target = tmp_path / "excel_mappings.yaml"
    target.write_text(yaml.safe_dump(data), encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        load_template_mapping(path=target)
