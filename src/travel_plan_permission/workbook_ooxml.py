"""Targeted OOXML updates that preserve organization workbook layout.

The FY2026 itinerary workbook contains large lookup sheets and formatting that
``openpyxl`` rewrites on save. This module changes only declared input cells in
the named worksheet and copies every other ZIP member unchanged.
"""

from __future__ import annotations

import re
import zipfile
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from pathlib import PurePosixPath
from typing import cast
from xml.etree import ElementTree as ET

_SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_DOCUMENT_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_XML_NS = "http://www.w3.org/XML/1998/namespace"
_DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
_X14_NS = "http://schemas.microsoft.com/office/spreadsheetml/2009/9/main"
_XR2_NS = "http://schemas.microsoft.com/office/spreadsheetml/2015/revision2"
_MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
_CELL_REF = re.compile(r"^[A-Z]{1,3}[1-9][0-9]*$")
_CALC_PR = re.compile(rb"<calcPr\b[^>]*/>")


class WorkbookTemplateError(ValueError):
    """Raised when a declared workbook worksheet or input cell has drifted."""


ET.register_namespace("", _SPREADSHEET_NS)
ET.register_namespace("r", _DOCUMENT_REL_NS)
ET.register_namespace("xdr", _DRAWING_NS)
ET.register_namespace("x14", _X14_NS)
ET.register_namespace("xr2", _XR2_NS)
ET.register_namespace("mc", _MC_NS)


def _tag(local_name: str) -> str:
    return f"{{{_SPREADSHEET_NS}}}{local_name}"


def _worksheet_member(archive: zipfile.ZipFile, worksheet_name: str) -> str:
    workbook_root = ET.fromstring(archive.read("xl/workbook.xml"))
    relationship_id: str | None = None
    for sheet in workbook_root.iter(_tag("sheet")):
        if sheet.attrib.get("name") == worksheet_name:
            relationship_id = sheet.attrib.get(f"{{{_DOCUMENT_REL_NS}}}id")
            break
    if relationship_id is None:
        available = [sheet.attrib.get("name", "") for sheet in workbook_root.iter(_tag("sheet"))]
        raise WorkbookTemplateError(
            f"Worksheet '{worksheet_name}' was not found; available worksheets: "
            f"{', '.join(available)}"
        )

    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    target: str | None = None
    relationship_tag = f"{{{_PACKAGE_REL_NS}}}Relationship"
    for relationship in relationships.iter(relationship_tag):
        if relationship.attrib.get("Id") == relationship_id:
            target = relationship.attrib.get("Target")
            break
    if target is None:
        raise WorkbookTemplateError(
            f"Worksheet '{worksheet_name}' relationship '{relationship_id}' was not found."
        )

    normalized = PurePosixPath(target.lstrip("/"))
    if normalized.parts and normalized.parts[0] == "xl":
        return str(normalized)
    return str(PurePosixPath("xl") / normalized)


def _excel_serial(value: date | datetime, *, date_1904: bool) -> Decimal:
    epoch = datetime(1904, 1, 1) if date_1904 else datetime(1899, 12, 30)
    moment = (
        value
        if isinstance(value, datetime)
        else datetime(value.year, value.month, value.day)
    )
    delta = moment - epoch
    return Decimal(delta.days) + Decimal(delta.seconds) / Decimal(86400)


def _write_cell_value(cell: ET.Element, value: object, *, date_1904: bool) -> None:
    for child_name in ("f", "v", "is"):
        child = cell.find(_tag(child_name))
        if child is not None:
            cell.remove(child)

    if isinstance(value, bool):
        cell.attrib["t"] = "b"
        ET.SubElement(cell, _tag("v")).text = "1" if value else "0"
        return
    if isinstance(value, date):
        cell.attrib.pop("t", None)
        ET.SubElement(cell, _tag("v")).text = format(
            _excel_serial(value, date_1904=date_1904), "f"
        )
        return
    if isinstance(value, Decimal | int | float):
        cell.attrib.pop("t", None)
        numeric = value if isinstance(value, Decimal) else Decimal(str(value))
        ET.SubElement(cell, _tag("v")).text = format(numeric, "f")
        return

    text = str(value)
    cell.attrib["t"] = "inlineStr"
    inline = ET.SubElement(cell, _tag("is"))
    text_node = ET.SubElement(inline, _tag("t"))
    if text != text.strip():
        text_node.attrib[f"{{{_XML_NS}}}space"] = "preserve"
    text_node.text = text


def _write_cell_formula(cell: ET.Element, formula: str) -> None:
    """Replace a formula while retaining the organization's cell style."""

    for child_name in ("f", "v", "is"):
        child = cell.find(_tag(child_name))
        if child is not None:
            cell.remove(child)
    ET.SubElement(cell, _tag("f")).text = formula.removeprefix("=")


def _update_worksheet(
    sheet_xml: bytes,
    cell_values: Mapping[str, object],
    cell_formulas: Mapping[str, str],
    *,
    date_1904: bool,
) -> bytes:
    root = ET.fromstring(sheet_xml)
    existing_cells = {
        cell.attrib["r"]: cell
        for cell in root.iter(_tag("c"))
        if "r" in cell.attrib
    }
    target_cells = set(cell_values) | set(cell_formulas)
    missing = [
        cell_ref
        for cell_ref in target_cells
        if not _CELL_REF.fullmatch(cell_ref) or cell_ref not in existing_cells
    ]
    if missing:
        raise WorkbookTemplateError(
            "Mapped input cells were not found in the organization worksheet: "
            + ", ".join(sorted(missing))
        )
    for cell_ref, formula in cell_formulas.items():
        _write_cell_formula(existing_cells[cell_ref], formula)
    for cell_ref, value in cell_values.items():
        _write_cell_value(existing_cells[cell_ref], value, date_1904=date_1904)
    return cast(bytes, ET.tostring(root, encoding="utf-8", xml_declaration=True))


def _date_1904_enabled(workbook_xml: bytes) -> bool:
    root = ET.fromstring(workbook_xml)
    workbook_properties = root.find(_tag("workbookPr"))
    if workbook_properties is None:
        return False
    return workbook_properties.attrib.get("date1904", "0").casefold() in {
        "1",
        "true",
    }


def _mark_full_calculation(workbook_xml: bytes) -> bytes:
    replacement = b'<calcPr calcMode="auto" fullCalcOnLoad="1" forceFullCalc="1"/>'
    if _CALC_PR.search(workbook_xml):
        return _CALC_PR.sub(replacement, workbook_xml, count=1)
    closing_tag = b"</workbook>"
    if closing_tag not in workbook_xml:
        raise WorkbookTemplateError("Workbook XML is missing its closing element.")
    return workbook_xml.replace(closing_tag, replacement + closing_tag, 1)


def render_mapped_workbook(
    template_bytes: bytes,
    *,
    worksheet_name: str,
    cell_values: Mapping[str, object],
    cell_formulas: Mapping[str, str] | None = None,
) -> bytes:
    """Return a layout-preserving copy with only mapped cells changed."""

    source = BytesIO(template_bytes)
    output = BytesIO()
    with zipfile.ZipFile(source) as archive:
        workbook_xml = archive.read("xl/workbook.xml")
        worksheet_member = _worksheet_member(archive, worksheet_name)
        replacements = {
            "xl/workbook.xml": _mark_full_calculation(workbook_xml),
            worksheet_member: _update_worksheet(
                archive.read(worksheet_member),
                cell_values,
                cell_formulas or {},
                date_1904=_date_1904_enabled(workbook_xml),
            ),
        }
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as rendered:
            for item in archive.infolist():
                rendered.writestr(item, replacements.get(item.filename, archive.read(item.filename)))
    return output.getvalue()
