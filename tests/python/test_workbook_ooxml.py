from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest
from openpyxl import load_workbook

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


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
        Decimal("NaN"),
        Decimal("sNaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
    ],
)
def test_render_mapped_workbook_blanks_non_finite_numbers(value: float | Decimal) -> None:
    template_bytes = _TEMPLATE.read_bytes()
    output_bytes = render_mapped_workbook(
        template_bytes,
        worksheet_name="Itinerary Form",
        cell_values={"C6": value, "G6": 123.5, "H6": Decimal("42.25")},
        cell_formulas={"C6": "=1+1"},
    )
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with ZipFile(BytesIO(template_bytes)) as source, ZipFile(BytesIO(output_bytes)) as output:
        source_root = ET.fromstring(source.read("xl/worksheets/sheet1.xml"))
        output_root = ET.fromstring(output.read("xl/worksheets/sheet1.xml"))
        original = source_root.find(".//s:c[@r='C6']", ns)
        cell = output_root.find(".//s:c[@r='C6']", ns)
        assert original is not None and cell is not None
        assert cell.attrib == {key: val for key, val in original.attrib.items() if key != "t"}
        assert list(cell) == []
        assert source.namelist() == output.namelist()
        for member in source.namelist():
            if member not in {"xl/workbook.xml", "xl/worksheets/sheet1.xml"}:
                assert source.read(member) == output.read(member)

    workbook = load_workbook(BytesIO(output_bytes), data_only=True)
    try:
        worksheet = workbook["Itinerary Form"]
        assert worksheet["C6"].value is None
        assert worksheet["G6"].value == 123.5
        assert worksheet["H6"].value == 42.25
    finally:
        workbook.close()


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
            member for member in source.namelist() if source.read(member) != output.read(member)
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
