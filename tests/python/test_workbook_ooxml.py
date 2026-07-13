from datetime import date
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from travel_plan_permission.workbook_ooxml import (
    WorkbookTemplateError,
    render_mapped_workbook,
)

_TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "travel_plan_permission"
    / "templates"
    / "Travel_Itinerary_Form_Jan_1_2026_runtime.xlsx"
)


def test_render_mapped_workbook_changes_only_workbook_and_target_worksheet() -> None:
    template_bytes = _TEMPLATE.read_bytes()

    output_bytes = render_mapped_workbook(
        template_bytes,
        worksheet_name="Itinerary Form",
        cell_values={"C6": "Layout Canary", "M7": date(2026, 10, 14)},
        cell_formulas={"H6": '=G6&" lookup"'},
    )

    with ZipFile(BytesIO(template_bytes)) as source, ZipFile(BytesIO(output_bytes)) as output:
        assert source.namelist() == output.namelist()
        changed = {
            member
            for member in source.namelist()
            if source.read(member) != output.read(member)
        }
        assert changed == {"xl/workbook.xml", "xl/worksheets/sheet1.xml"}
        sheet_xml = output.read("xl/worksheets/sheet1.xml")
        assert b"Layout Canary" in sheet_xml
        assert b'G6&amp;" lookup"' in sheet_xml
        assert b'<calcPr calcMode="auto" fullCalcOnLoad="1" forceFullCalc="1"/>' in output.read(
            "xl/workbook.xml"
        )


@pytest.mark.parametrize(
    ("worksheet_name", "cell_values", "message"),
    [
        ("Missing Sheet", {"C6": "value"}, "Worksheet 'Missing Sheet' was not found"),
        ("Itinerary Form", {"Z999": "value"}, "Mapped input cells were not found"),
    ],
)
def test_render_mapped_workbook_rejects_template_drift(
    worksheet_name: str,
    cell_values: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(WorkbookTemplateError, match=message):
        render_mapped_workbook(
            _TEMPLATE.read_bytes(),
            worksheet_name=worksheet_name,
            cell_values=cell_values,
        )
