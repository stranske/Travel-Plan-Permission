"""OpenPyXL workbook population boundary for legacy spreadsheet rendering."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from openpyxl.workbook import Workbook

from .canonical import CanonicalTripPlan
from .mapping import TemplateMapping
from .models import TripPlan


def populate_travel_workbook(
    wb: Workbook,
    plan: TripPlan,
    mapping: TemplateMapping,
    *,
    canonical_plan: CanonicalTripPlan | None,
    report: Any | None,
    mapped_cell_values: Callable[..., list[Any]],
) -> None:
    """Populate configured cells and formulas while preserving workbook structure."""
    worksheet_name = mapping.metadata.get("worksheet")
    if isinstance(worksheet_name, str):
        if worksheet_name not in wb.sheetnames:
            raise ValueError(
                f"Template worksheet '{worksheet_name}' was not found; available worksheets: {', '.join(wb.sheetnames)}"
            )
        worksheet = wb[worksheet_name]
    else:
        worksheet = wb.active
    for mapped_value in mapped_cell_values(
        plan, mapping, canonical_plan=canonical_plan, report=report
    ):
        worksheet[mapped_value.cell] = mapped_value.value
        if mapped_value.number_format is not None:
            worksheet[mapped_value.cell].number_format = mapped_value.number_format
    for formula_config in mapping.formulas.values():
        cell, formula = formula_config.get("cell"), formula_config.get("formula")
        if isinstance(cell, str) and isinstance(formula, str):
            worksheet[cell] = formula
