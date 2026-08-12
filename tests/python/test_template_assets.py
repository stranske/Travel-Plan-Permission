from hashlib import sha256
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
    worksheet_name = mapping.metadata.get("worksheet")
    assert isinstance(worksheet_name, str)
    sheet = workbook[worksheet_name]

    for cell_ref in mapping.cells.values():
        coordinate_from_string(cell_ref)
        assert sheet[cell_ref].style_id != 0

    for checkbox_config in mapping.checkboxes.values():
        cell_ref = checkbox_config.get("cell")
        assert isinstance(cell_ref, str)
        coordinate_from_string(cell_ref)
        assert sheet[cell_ref].style_id != 0

    for formula_config in mapping.formulas.values():
        cell_ref = formula_config.get("cell")
        formula = formula_config.get("formula")
        assert isinstance(cell_ref, str)
        assert isinstance(formula, str)
        assert isinstance(sheet[cell_ref].value, str)
        assert sheet[cell_ref].value.startswith("=")

    source_file = mapping.metadata.get("source_file")
    source_sha256 = mapping.metadata.get("source_sha256")
    runtime_sha256 = mapping.metadata.get("runtime_sha256")
    assert isinstance(source_file, str)
    assert isinstance(source_sha256, str)
    assert isinstance(runtime_sha256, str)
    source_path = Path(source_file)
    assert sha256(source_path.read_bytes()).hexdigest() == source_sha256
    assert sha256(template_path.read_bytes()).hexdigest() == runtime_sha256
    workbook.close()


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
