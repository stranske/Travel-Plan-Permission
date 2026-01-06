import json
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook

import travel_plan_permission.policy_api as policy_api
from travel_plan_permission import (
    ExpenseCategory,
    TripPlan,
    fill_travel_spreadsheet,
    render_travel_spreadsheet_bytes,
)
from travel_plan_permission.canonical import CanonicalTripPlan, canonical_trip_plan_to_model
from travel_plan_permission.mapping import TemplateMapping


def _plan() -> TripPlan:
    return TripPlan(
        trip_id="TRIP-XL-001",
        traveler_name="Jordan Lee",
        department="FIN-OPS",
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


def test_travel_spreadsheet_template_loads() -> None:
    template_path = policy_api._default_template_path()
    assert template_path.is_file()

    workbook = load_workbook(template_path)

    assert workbook.sheetnames
    workbook.close()


def test_fill_travel_spreadsheet_writes_mapped_fields(tmp_path) -> None:
    plan = _plan()
    output_path = tmp_path / "filled.xlsx"

    result = fill_travel_spreadsheet(plan, output_path)

    assert result == output_path
    workbook = load_workbook(output_path)
    sheet = workbook.active

    assert sheet["B3"].value == plan.traveler_name
    assert sheet["B4"].value == plan.purpose
    assert sheet["D4"].value == plan.department
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
    workbook.close()


def test_render_travel_spreadsheet_bytes_returns_xlsx_bytes() -> None:
    plan = _plan()

    output_bytes = render_travel_spreadsheet_bytes(plan)

    workbook = load_workbook(BytesIO(output_bytes))
    assert workbook.sheetnames
    workbook.close()


def test_fill_travel_spreadsheet_matches_rendered_bytes(tmp_path) -> None:
    plan = _plan()
    output_path = tmp_path / "filled-match.xlsx"

    output_bytes = render_travel_spreadsheet_bytes(plan)
    fill_travel_spreadsheet(plan, output_path)

    # Compare workbook contents instead of raw bytes (which include timestamps)
    wb_from_bytes = load_workbook(BytesIO(output_bytes))
    wb_from_file = load_workbook(output_path)

    # Compare sheet names
    assert wb_from_bytes.sheetnames == wb_from_file.sheetnames

    # Compare cell values in all sheets
    for sheet_name in wb_from_bytes.sheetnames:
        sheet_bytes = wb_from_bytes[sheet_name]
        sheet_file = wb_from_file[sheet_name]

        # Compare all cell values
        for row in sheet_bytes.iter_rows():
            for cell in row:
                file_cell = sheet_file[cell.coordinate]
                assert file_cell.value == cell.value, f"Mismatch at {cell.coordinate}"

    wb_from_bytes.close()
    wb_from_file.close()


def test_fill_travel_spreadsheet_rounds_currency_values(tmp_path) -> None:
    plan = _plan().model_copy(
        update={
            "expense_breakdown": {
                ExpenseCategory.AIRFARE: Decimal("450.567"),
            }
        }
    )
    output_path = tmp_path / "filled-rounded.xlsx"

    fill_travel_spreadsheet(plan, output_path)

    workbook = load_workbook(output_path)
    sheet = workbook.active

    assert sheet["E8"].value == 450.57
    assert sheet["E8"].number_format == "$#,##0.00"
    workbook.close()


def test_fill_travel_spreadsheet_does_not_modify_template(tmp_path) -> None:
    template_path = policy_api._default_template_path()
    template_bytes = template_path.read_bytes()
    plan = _plan()
    output_path = tmp_path / "filled.xlsx"

    fill_travel_spreadsheet(plan, output_path)

    assert output_path.is_file()
    assert template_path.read_bytes() == template_bytes


def test_fill_travel_spreadsheet_uses_mapping_cells(tmp_path, monkeypatch) -> None:
    plan = _plan()
    output_path = tmp_path / "filled-custom.xlsx"
    mapping = TemplateMapping(
        version="ITIN-2025.1",
        cells={
            "traveler_name": "Z99",
            "depart_date": "Z100",
            "event_registration_cost": "Z101",
        },
        dropdowns={},
        checkboxes={},
        formulas={},
        metadata={},
    )

    monkeypatch.setattr(policy_api, "load_template_mapping", lambda: mapping)

    fill_travel_spreadsheet(plan, output_path)

    workbook = load_workbook(output_path)
    sheet = workbook.active

    assert sheet["Z99"].value == plan.traveler_name
    assert sheet["Z100"].value == "2024-09-15"
    assert sheet["Z101"].value == 200.0
    assert sheet["Z101"].number_format == "$#,##0.00"
    workbook.close()


def test_fill_travel_spreadsheet_uses_template_metadata(tmp_path, monkeypatch) -> None:
    plan = _plan()
    output_path = tmp_path / "filled-template.xlsx"
    template_path = policy_api._default_template_path()
    template_bytes = template_path.read_bytes()
    observed: dict[str, object] = {}

    def fake_default_template_bytes(template_file: str | None = None):
        observed["template_file"] = template_file
        return template_bytes

    mapping = TemplateMapping(
        version="ITIN-2025.1",
        cells={"traveler_name": "B3"},
        dropdowns={},
        checkboxes={},
        formulas={},
        metadata={"template_file": "custom_template.xlsx"},
    )

    monkeypatch.setattr(policy_api, "load_template_mapping", lambda: mapping)
    monkeypatch.setattr(policy_api, "_default_template_bytes", fake_default_template_bytes)

    fill_travel_spreadsheet(plan, output_path)

    assert observed["template_file"] == "custom_template.xlsx"


def test_fill_travel_spreadsheet_uses_canonical_fields(tmp_path) -> None:
    fixture_path = (
        Path(__file__).resolve().parents[1] / "fixtures" / "sample_trip_plan_minimal.json"
    )
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    canonical_plan = CanonicalTripPlan.model_validate(payload)
    trip_plan = canonical_trip_plan_to_model(canonical_plan)
    output_path = tmp_path / "filled-canonical.xlsx"

    fill_travel_spreadsheet(trip_plan, output_path, canonical_plan=canonical_plan)

    workbook = load_workbook(output_path)
    sheet = workbook.active

    assert canonical_plan.hotel is not None
    assert sheet["B11"].value == canonical_plan.hotel.name
    assert sheet["B12"].value == canonical_plan.hotel.address
    assert sheet["G12"].value == "X"
    assert sheet["B15"].value == "rideshare/taxi"
    workbook.close()


def test_fill_travel_spreadsheet_populates_flight_and_hotel_preferences(tmp_path) -> None:
    fixture_path = (
        Path(__file__).resolve().parents[1] / "fixtures" / "sample_trip_plan_rich.json"
    )
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    canonical_plan = CanonicalTripPlan.model_validate(payload)
    trip_plan = canonical_trip_plan_to_model(canonical_plan)
    output_path = tmp_path / "filled-rich.xlsx"

    fill_travel_spreadsheet(trip_plan, output_path, canonical_plan=canonical_plan)

    workbook = load_workbook(output_path)
    sheet = workbook.active

    assert sheet["B8"].value == "UA204"
    assert sheet["C8"].value == "2025-11-12T09:10"
    assert sheet["D8"].value == "2025-11-12T12:45"
    assert sheet["E8"].value == 612.4
    assert sheet["B9"].value == "UA205"
    assert sheet["C9"].value == "2025-11-16T16:05"
    assert sheet["D9"].value == "2025-11-16T19:30"
    assert sheet["B11"].value == "Harborview Suites"
    assert sheet["B12"].value == "88 Mission St"
    assert sheet["D12"].value == "San Francisco, CA"
    assert sheet["E12"].value == 289.9
    assert sheet["F12"].value == 4
    assert sheet["G12"].value in (None, "")
    assert sheet["B13"].value == "Conference hotel was $60 more per night"
    assert sheet["B14"].value == "Market Square Inn"
    assert sheet["C14"].value == 249.0
    assert sheet["B15"].value == "rental car"
    assert sheet["B16"].value == "Need early check-in and airport pickup."
    workbook.close()
