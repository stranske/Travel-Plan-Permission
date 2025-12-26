from openpyxl import load_workbook
from openpyxl.utils.cell import coordinate_from_string

from travel_plan_permission import policy_api
from travel_plan_permission.mapping import load_template_mapping


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
