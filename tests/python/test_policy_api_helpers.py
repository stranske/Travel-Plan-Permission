from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

import travel_plan_permission.policy_api as policy_api
from travel_plan_permission import ExpenseCategory, TripPlan
from travel_plan_permission.mapping import TemplateMapping
from travel_plan_permission.policy import PolicyResult, Severity


def _blank_template_bytes(initial_cells: dict[str, object] | None = None) -> bytes:
    wb = Workbook()
    ws = wb.active
    for cell, value in (initial_cells or {}).items():
        ws[cell] = value
    buffer = BytesIO()
    wb.save(buffer)
    wb.close()
    return buffer.getvalue()


@pytest.fixture()
def base_plan() -> TripPlan:
    return TripPlan(
        trip_id="TRIP-HELP-001",
        traveler_name="Taylor Morgan",
        department="FIN",
        destination="Austin, TX 78701",
        departure_date=date(2024, 9, 15),
        return_date=date(2024, 9, 20),
        purpose="Planning session",
        transportation_mode="air",
        estimated_cost=Decimal("1500.00"),
        expense_breakdown={ExpenseCategory.CONFERENCE_FEES: Decimal("0")},
    )


def test_default_template_path_reports_package_resource_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResource:
        def joinpath(self, *_parts: str) -> FakeResource:
            return self

        def is_file(self) -> bool:
            return True

    monkeypatch.setattr(Path, "exists", lambda _self: False)
    monkeypatch.setattr(policy_api.resources, "files", lambda _name: FakeResource())

    with pytest.raises(FileNotFoundError, match="path access not supported"):
        policy_api._default_template_path("missing-template.xlsx")


def test_default_template_bytes_reads_package_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template_bytes = b"template-bytes"

    class FakeResource:
        def joinpath(self, *_parts: str) -> FakeResource:
            return self

        def is_file(self) -> bool:
            return True

        def read_bytes(self) -> bytes:
            return template_bytes

    monkeypatch.setattr(Path, "exists", lambda _self: False)
    monkeypatch.setattr(policy_api.resources, "files", lambda _name: FakeResource())

    assert policy_api._default_template_bytes("missing-template.xlsx") == template_bytes


def test_default_template_bytes_missing_package_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "exists", lambda _self: False)

    def _raise_module_error(_name: str):
        raise ModuleNotFoundError

    monkeypatch.setattr(policy_api.resources, "files", _raise_module_error)

    with pytest.raises(FileNotFoundError, match="Unable to locate templates"):
        policy_api._default_template_bytes("missing-template.xlsx")


def test_split_destination_returns_original_when_pattern_misses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(policy_api, "_ZIP_PATTERN", re.compile(r"^$"))

    city_state, zip_code = policy_api._split_destination("Nowhere Land 99999")

    assert city_state == "Nowhere Land 99999"
    assert zip_code is None


def test_resolve_field_value_handles_nested_variations() -> None:
    assert policy_api._resolve_field_value({"a": 1}, "a") == 1
    assert policy_api._resolve_field_value({"a": 1}, "bad[") is None
    assert policy_api._resolve_field_value({"a": "value"}, "a.b") is None
    assert policy_api._resolve_field_value({"a": {"b": "value"}}, "a.b[0]") is None
    assert policy_api._resolve_field_value({"a": {"b": [1]}}, "a.b[2]") is None
    assert policy_api._resolve_field_value({"a": {"b": [{"c": 3}]}}, "a.b[0].c") == 3


def test_format_date_value_variants() -> None:
    assert policy_api._format_date_value(datetime(2024, 1, 2, 9, 30)) == "2024-01-02"
    assert policy_api._format_date_value(date(2024, 2, 3)) == "2024-02-03"
    assert policy_api._format_date_value("2024-03-04") == "2024-03-04"
    assert policy_api._format_date_value(123) is None


def test_format_currency_value_variants() -> None:
    assert policy_api._format_currency_value(None) is None
    assert policy_api._format_currency_value(10) == Decimal("10.00")
    assert policy_api._format_currency_value(12.5) == Decimal("12.50")
    assert policy_api._format_currency_value("oops") is None
    assert policy_api._format_currency_value(object()) is None


def test_issue_severity_reports_info() -> None:
    result = PolicyResult(
        rule_id="info_rule",
        severity=Severity.INFO,
        passed=True,
        message="Informational",
    )

    assert policy_api._issue_severity(result) == "info"


def test_fill_travel_spreadsheet_sets_dropdown_checkbox_and_formula(
    base_plan: TripPlan, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mapping = TemplateMapping(
        version="ITIN-2025.1",
        cells={"traveler_name": "A1"},
        dropdowns={"transportation_mode": {"cell": "B1"}},
        checkboxes={
            "department": {"cell": "C1", "true_value": "Y", "false_value": "N"}
        },
        formulas={"total": {"cell": "D1", "formula": "=1+1"}},
        metadata={},
    )
    template_bytes = _blank_template_bytes()

    monkeypatch.setattr(policy_api, "load_template_mapping", lambda: mapping)
    monkeypatch.setattr(
        policy_api,
        "_default_template_bytes",
        lambda *_args, **_kwargs: template_bytes,
    )

    output_path = tmp_path / "dropdowns.xlsx"
    policy_api.fill_travel_spreadsheet(base_plan, output_path)

    workbook = load_workbook(output_path)
    sheet = workbook.active
    assert sheet["A1"].value == base_plan.traveler_name
    assert sheet["B1"].value == base_plan.transportation_mode
    assert sheet["C1"].value == "Y"
    assert sheet["D1"].value == "=1+1"
    workbook.close()


def test_fill_travel_spreadsheet_skips_invalid_currency_and_date(
    base_plan: TripPlan, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mapping = TemplateMapping(
        version="ITIN-2025.1",
        cells={"event_registration_cost": "B2", "depart_date": "C2"},
        dropdowns={},
        checkboxes={},
        formulas={},
        metadata={},
    )
    template_bytes = _blank_template_bytes({"B2": "keep", "C2": "keep"})

    monkeypatch.setattr(policy_api, "load_template_mapping", lambda: mapping)
    monkeypatch.setattr(
        policy_api,
        "_default_template_bytes",
        lambda *_args, **_kwargs: template_bytes,
    )
    monkeypatch.setattr(
        policy_api,
        "_plan_field_values",
        lambda _plan: {
            "event_registration_cost": "not-a-number",
            "depart_date": object(),
        },
    )

    output_path = tmp_path / "skips.xlsx"
    policy_api.fill_travel_spreadsheet(base_plan, output_path)

    workbook = load_workbook(output_path)
    sheet = workbook.active
    assert sheet["B2"].value == "keep"
    assert sheet["C2"].value == "keep"
    workbook.close()
