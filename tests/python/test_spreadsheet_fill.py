from datetime import date
from decimal import Decimal

from openpyxl import load_workbook

from travel_plan_permission import (
    ExpenseCategory,
    TripPlan,
    fill_travel_spreadsheet,
)


def _plan() -> TripPlan:
    return TripPlan(
        trip_id="TRIP-XL-001",
        traveler_name="Jordan Lee",
        destination="Austin, TX 78701",
        departure_date=date(2024, 9, 15),
        return_date=date(2024, 9, 20),
        purpose="Conference planning",
        estimated_cost=Decimal("1200.00"),
        expense_breakdown={
            ExpenseCategory.CONFERENCE_FEES: Decimal("200"),
            ExpenseCategory.AIRFARE: Decimal("450.50"),
            ExpenseCategory.GROUND_TRANSPORT: Decimal("40"),
        },
    )


def test_fill_travel_spreadsheet_writes_mapped_fields(tmp_path) -> None:
    plan = _plan()
    output_path = tmp_path / "filled.xlsx"

    result = fill_travel_spreadsheet(plan, output_path)

    assert result == output_path
    workbook = load_workbook(output_path)
    sheet = workbook.active

    assert sheet["B3"].value == plan.traveler_name
    assert sheet["B4"].value == plan.purpose
    assert sheet["B5"].value == "Austin, TX"
    assert sheet["F5"].value == "78701"
    assert sheet["B6"].value == "2024-09-15"
    assert sheet["D6"].value == "2024-09-20"
    assert sheet["F6"].value == 200.0
    assert sheet["F6"].number_format == "$#,##0.00"
    assert sheet["E8"].value == 450.5
    assert sheet["E8"].number_format == "$#,##0.00"
    assert sheet["E9"].value == 450.5
    assert sheet["E9"].number_format == "$#,##0.00"
    assert sheet["F9"].value == 40.0
    assert sheet["F9"].number_format == "$#,##0.00"
