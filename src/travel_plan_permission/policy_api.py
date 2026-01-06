"""Stable policy API surface for orchestration integrations."""

from __future__ import annotations

import re
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import date, datetime
from decimal import Decimal
from importlib import resources
from io import BytesIO
from pathlib import Path
from typing import Literal

from openpyxl import load_workbook  # type: ignore[import-untyped]
from openpyxl.workbook import Workbook  # type: ignore[import-untyped]
from pydantic import BaseModel, Field

from .canonical import CanonicalTripPlan
from .mapping import TemplateMapping, load_template_mapping
from .models import ExpenseCategory, ExpenseItem, ExpenseReport, TripPlan
from .policy import PolicyContext, PolicyEngine, PolicyResult, Severity
from .policy_versioning import PolicyVersion
from .providers import ProviderRegistry, ProviderType
from .receipts import Receipt, summarize_receipts

PolicyIssueSeverity = Literal["info", "warning", "error"]
PolicyCheckStatus = Literal["pass", "fail"]
ReconciliationStatus = Literal["under_budget", "on_budget", "over_budget"]
PolicyIssueContextValue = str | int | float | bool | None

__all__ = [
    "PolicyIssueSeverity",
    "PolicyCheckStatus",
    "ReconciliationStatus",
    "PolicyIssue",
    "PolicyCheckResult",
    "ReconciliationResult",
    "UnfilledMappingEntry",
    "UnfilledMappingReport",
    "TripPlan",
    "Receipt",
    "check_trip_plan",
    "fill_travel_spreadsheet",
    "list_allowed_vendors",
    "reconcile",
]


class PolicyIssue(BaseModel):
    """Single policy rule violation or advisory."""

    code: str = Field(..., description="Stable policy rule code")
    message: str = Field(..., description="Human-readable policy message")
    severity: PolicyIssueSeverity = Field(..., description="Severity of the issue")
    context: dict[str, PolicyIssueContextValue] = Field(
        default_factory=dict, description="Additional rule context"
    )


class PolicyCheckResult(BaseModel):
    """Aggregated policy check results for a trip plan."""

    status: PolicyCheckStatus = Field(..., description="Pass/fail status")
    issues: list[PolicyIssue] = Field(
        default_factory=list, description="Policy issues raised by the check"
    )
    policy_version: str = Field(..., description="Deterministic policy version identifier")


class ReconciliationResult(BaseModel):
    """Summary of post-trip expense reconciliation."""

    trip_id: str = Field(..., description="Trip identifier")
    report_id: str = Field(..., description="Generated expense report identifier")
    planned_total: Decimal = Field(..., description="Estimated trip total")
    actual_total: Decimal = Field(..., description="Actual reconciled spend")
    variance: Decimal = Field(..., description="Actual minus planned spend variance")
    status: ReconciliationStatus = Field(..., description="Budget reconciliation status")
    receipt_count: int = Field(..., ge=0, description="Number of receipts")
    receipts_by_type: dict[str, int] = Field(
        default_factory=dict, description="Receipt counts by file type"
    )
    expenses_by_category: dict[ExpenseCategory, Decimal] = Field(
        default_factory=dict, description="Actual spend grouped by category"
    )


@dataclass(frozen=True)
class UnfilledMappingEntry:
    """Details for a mapping entry that could not be populated."""

    field: str
    cell: str | None
    reason: str


@dataclass
class UnfilledMappingReport:
    """Structured summary of unfilled mapping entries."""

    cells: list[UnfilledMappingEntry] = dataclass_field(default_factory=list)
    dropdowns: list[UnfilledMappingEntry] = dataclass_field(default_factory=list)
    checkboxes: list[UnfilledMappingEntry] = dataclass_field(default_factory=list)

    def add(self, section: str, field: str, cell: str | None, reason: str) -> None:
        entry = UnfilledMappingEntry(field=field, cell=cell, reason=reason)
        if section == "cells":
            self.cells.append(entry)
        elif section == "dropdowns":
            self.dropdowns.append(entry)
        elif section == "checkboxes":
            self.checkboxes.append(entry)


_TEMPLATE_FILENAME = "travel_request_template.xlsx"
_CURRENCY_FIELDS = {
    "event_registration_cost",
    "flight_pref_outbound.roundtrip_cost",
    "lowest_cost_roundtrip",
    "parking_estimate",
    "hotel.nightly_rate",
    "comparable_hotels[0].nightly_rate",
}
_DATE_FIELDS = {"depart_date", "return_date"}
_CURRENCY_FORMAT = "$#,##0.00"
_ZIP_PATTERN = re.compile(r"^(?P<city_state>.*?)(?:\s+(?P<zip>\d{5})(?:-\d{4})?)?$")
_RESOURCE_TEMPLATE_CACHE: dict[str, Path] = {}


def _default_template_path(template_file: str | None = None) -> Path:
    """Return path to the default template file."""
    template_name = template_file or _TEMPLATE_FILENAME
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "templates" / template_name
        if candidate.exists():
            return candidate
    try:
        resource = resources.files("travel_plan_permission").joinpath("templates", template_name)
    except ModuleNotFoundError:
        resource = None
    if resource is not None and resource.is_file():
        cached_path = _RESOURCE_TEMPLATE_CACHE.get(template_name)
        if cached_path is not None and cached_path.exists():
            return cached_path
        temp_dir = tempfile.mkdtemp(prefix="travel_plan_template_")
        temp_path = Path(temp_dir) / template_name
        temp_path.write_bytes(resource.read_bytes())
        _RESOURCE_TEMPLATE_CACHE[template_name] = temp_path
        return temp_path
    raise FileNotFoundError(f"Unable to locate templates/{template_name}")


def _default_template_bytes(template_file: str | None = None) -> bytes:
    template_name = template_file or _TEMPLATE_FILENAME
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "templates" / template_name
        if candidate.exists():
            return candidate.read_bytes()
    try:
        resource = resources.files("travel_plan_permission").joinpath("templates", template_name)
    except ModuleNotFoundError:
        resource = None
    if resource is not None and resource.is_file():
        return resource.read_bytes()
    raise FileNotFoundError(f"Unable to locate templates/{template_name}")


def _split_destination(destination: str) -> tuple[str, str | None]:
    match = _ZIP_PATTERN.match(destination.strip())
    if not match:
        return destination, None
    city_state = (match.group("city_state") or "").strip()
    zip_code = match.group("zip")
    return (city_state or destination), zip_code


def _plan_field_values(
    plan: TripPlan, canonical_plan: CanonicalTripPlan | None = None
) -> dict[str, object]:
    if canonical_plan is not None:
        city_state = canonical_plan.city_state or ""
        zip_code: str | None = canonical_plan.destination_zip
    else:
        city_state, zip_code = _split_destination(plan.destination)
    fields: dict[str, object] = dict(plan.model_dump())
    if canonical_plan is not None:
        fields.update(canonical_plan.model_dump())
    fields.update(
        {
            "traveler_name": canonical_plan.traveler_name if canonical_plan else plan.traveler_name,
            "business_purpose": (
                canonical_plan.business_purpose if canonical_plan else plan.purpose
            ),
            "cost_center": (
                canonical_plan.cost_center
                if canonical_plan and canonical_plan.cost_center is not None
                else plan.department or plan.funding_source
            ),
            "city_state": city_state,
            "destination_zip": zip_code,
            "depart_date": canonical_plan.depart_date if canonical_plan else plan.departure_date,
            "return_date": canonical_plan.return_date if canonical_plan else plan.return_date,
            "event_registration_cost": (
                canonical_plan.event_registration_cost
                if canonical_plan and canonical_plan.event_registration_cost is not None
                else plan.expense_breakdown.get(ExpenseCategory.CONFERENCE_FEES)
            ),
            "flight_pref_outbound.roundtrip_cost": (
                canonical_plan.flight_pref_outbound.roundtrip_cost
                if canonical_plan
                and canonical_plan.flight_pref_outbound is not None
                and canonical_plan.flight_pref_outbound.roundtrip_cost is not None
                else plan.expense_breakdown.get(ExpenseCategory.AIRFARE)
            ),
            "lowest_cost_roundtrip": (
                canonical_plan.lowest_cost_roundtrip
                if canonical_plan and canonical_plan.lowest_cost_roundtrip is not None
                else plan.expense_breakdown.get(ExpenseCategory.AIRFARE)
            ),
            "parking_estimate": (
                canonical_plan.parking_estimate
                if canonical_plan and canonical_plan.parking_estimate is not None
                else plan.expense_breakdown.get(ExpenseCategory.GROUND_TRANSPORT)
            ),
        }
    )
    return fields


def _resolve_field_value(data: object, field_name: str) -> object | None:
    if isinstance(data, dict) and field_name in data:
        result: object = data[field_name]
        return result

    current: object = data
    for segment in field_name.split("."):
        match = re.match(r"^(?P<name>[^\[]+)(?:\[(?P<index>\d+)\])?$", segment)
        if not match:
            return None
        name = match.group("name")
        index_raw = match.group("index")
        if not isinstance(current, dict) or name not in current:
            return None
        current = current[name]
        if index_raw is not None:
            if not isinstance(current, list):
                return None
            index = int(index_raw)
            if index >= len(current):
                return None
            current = current[index]
    return current


def _format_date_value(value: object) -> str | None:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return value
    return None


def _format_currency_value(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, int | float):
        amount = Decimal(str(value))
    elif isinstance(value, str):
        try:
            amount = Decimal(value)
        except Exception:
            return None
    else:
        return None
    return amount.quantize(Decimal("0.01"))


def _normalize_dropdown_value(value: object, options: object) -> object:
    if not isinstance(value, str) or not isinstance(options, list):
        return value
    normalized = value.strip().casefold()
    for option in options:
        option_str = str(option)
        if normalized == option_str.strip().casefold():
            return option
    for option in options:
        option_str = str(option)
        if option_str.strip().casefold().startswith(normalized):
            return option
    return value


def _policy_version(engine: PolicyEngine) -> str:
    rule_config = {"rules": engine.describe_rules()}
    version = PolicyVersion.from_config(None, rule_config)
    return version.config_hash


def _expected_cost_value(plan: TripPlan, *keys: str) -> Decimal | None:
    for key in keys:
        if key not in plan.expected_costs:
            continue
        amount = _format_currency_value(plan.expected_costs.get(key))
        if amount is not None:
            return amount
    return None


def _context_from_plan(plan: TripPlan) -> PolicyContext:
    driving_cost = plan.driving_cost
    if driving_cost is None:
        driving_cost = plan.expense_breakdown.get(ExpenseCategory.GROUND_TRANSPORT)
    if driving_cost is None:
        driving_cost = _expected_cost_value(plan, "driving_cost", "ground_transport")

    flight_cost = plan.flight_cost
    if flight_cost is None:
        flight_cost = plan.expense_breakdown.get(ExpenseCategory.AIRFARE)
    if flight_cost is None:
        flight_cost = _expected_cost_value(plan, "flight_cost", "airfare")

    selected_fare = plan.selected_fare
    if selected_fare is None:
        selected_fare = _expected_cost_value(
            plan, "selected_fare", "flight_pref_outbound.roundtrip_cost", "airfare"
        )
    if selected_fare is None:
        selected_fare = flight_cost

    lowest_fare = plan.lowest_fare
    if lowest_fare is None:
        lowest_fare = _expected_cost_value(plan, "lowest_fare", "lowest_cost_roundtrip")

    return PolicyContext(
        booking_date=plan.booking_date,
        departure_date=plan.departure_date,
        return_date=plan.return_date,
        selected_fare=selected_fare,
        lowest_fare=lowest_fare,
        cabin_class=plan.cabin_class,
        flight_duration_hours=plan.flight_duration_hours,
        fare_evidence_attached=plan.fare_evidence_attached,
        driving_cost=driving_cost,
        flight_cost=flight_cost,
        comparable_hotels=plan.comparable_hotels,
        distance_from_office_miles=plan.distance_from_office_miles,
        overnight_stay=plan.overnight_stay,
        meals_provided=plan.meals_provided,
        meal_per_diem_requested=plan.meal_per_diem_requested,
        expenses=plan.expenses,
        third_party_payments=plan.third_party_payments,
    )


def _issue_severity(result: PolicyResult) -> PolicyIssueSeverity:
    if result.severity == Severity.BLOCKING:
        return "error"
    if result.severity == Severity.ADVISORY:
        return "warning"
    return "info"


def _issue_from_result(result: PolicyResult) -> PolicyIssue:
    return PolicyIssue(
        code=result.rule_id,
        message=result.message,
        severity=_issue_severity(result),
        context={"rule_id": result.rule_id, "severity": result.severity},
    )


def check_trip_plan(plan: TripPlan) -> PolicyCheckResult:
    """Evaluate a trip plan using the policy-lite engine."""

    engine = PolicyEngine.from_file()
    context = _context_from_plan(plan)
    results = engine.validate(context)
    issues = [_issue_from_result(result) for result in results if not result.passed]
    has_blocking = any(
        not result.passed and result.severity == Severity.BLOCKING for result in results
    )
    status: PolicyCheckStatus = "fail" if has_blocking else "pass"
    return PolicyCheckResult(status=status, issues=issues, policy_version=_policy_version(engine))


def list_allowed_vendors(plan: TripPlan) -> list[str]:
    """Return approved vendors for the trip destination."""

    registry = ProviderRegistry.from_file()
    destination = plan.destination
    reference_date = plan.departure_date
    providers = {
        provider.name
        for provider_type in ProviderType
        for provider in registry.lookup(provider_type, destination, reference_date=reference_date)
    }
    return sorted(providers, key=str.lower)


def _populate_travel_workbook(
    wb: Workbook,
    plan: TripPlan,
    mapping: TemplateMapping,
    *,
    canonical_plan: CanonicalTripPlan | None = None,
    report: UnfilledMappingReport | None = None,
) -> None:
    ws = wb.active
    field_data = _plan_field_values(plan, canonical_plan=canonical_plan)
    for field_name, cell in mapping.cells.items():
        value = _resolve_field_value(field_data, field_name)
        if value is None:
            if report is not None:
                report.add("cells", field_name, cell, "missing")
            continue
        if field_name in _CURRENCY_FIELDS:
            amount = _format_currency_value(value)
            if amount is None:
                if report is not None:
                    report.add("cells", field_name, cell, "invalid_currency")
                continue
            ws[cell] = float(amount)
            ws[cell].number_format = _CURRENCY_FORMAT
            continue
        if field_name in _DATE_FIELDS or isinstance(value, date):
            formatted = _format_date_value(value)
            if formatted is None:
                if report is not None:
                    report.add("cells", field_name, cell, "invalid_date")
                continue
            ws[cell] = formatted
            continue
        ws[cell] = value

    for field_name, dropdown_config in mapping.dropdowns.items():
        value = _resolve_field_value(field_data, field_name)
        if value is None:
            if report is not None:
                dropdown_cell = dropdown_config.get("cell")
                report.add(
                    "dropdowns",
                    field_name,
                    dropdown_cell if isinstance(dropdown_cell, str) else None,
                    "missing",
                )
            continue
        dropdown_cell = dropdown_config.get("cell")
        if isinstance(dropdown_cell, str):
            options = dropdown_config.get("options")
            ws[dropdown_cell] = _normalize_dropdown_value(value, options)

    for field_name, checkbox_config in mapping.checkboxes.items():
        value = _resolve_field_value(field_data, field_name)
        if value is None:
            if report is not None:
                checkbox_cell = checkbox_config.get("cell")
                report.add(
                    "checkboxes",
                    field_name,
                    checkbox_cell if isinstance(checkbox_cell, str) else None,
                    "missing",
                )
            continue
        checkbox_cell = checkbox_config.get("cell")
        if not isinstance(checkbox_cell, str):
            continue
        true_value = checkbox_config.get("true_value", "X")
        false_value = checkbox_config.get("false_value", "")
        ws[checkbox_cell] = true_value if bool(value) else false_value

    for formula_config in mapping.formulas.values():
        formula_cell = formula_config.get("cell")
        formula_value = formula_config.get("formula")
        if isinstance(formula_cell, str) and isinstance(formula_value, str):
            ws[formula_cell] = formula_value


def render_travel_spreadsheet_bytes(
    plan: TripPlan,
    *,
    canonical_plan: CanonicalTripPlan | None = None,
    report: UnfilledMappingReport | None = None,
) -> bytes:
    """Render a travel request spreadsheet to a .xlsx byte stream."""

    mapping = load_template_mapping()
    template_file = mapping.metadata.get("template_file")
    template_bytes = _default_template_bytes(
        template_file if isinstance(template_file, str) else None
    )
    wb = load_workbook(BytesIO(template_bytes))
    _populate_travel_workbook(
        wb,
        plan,
        mapping,
        canonical_plan=canonical_plan,
        report=report,
    )
    output = BytesIO()
    wb.save(output)
    wb.close()
    return output.getvalue()


def fill_travel_spreadsheet(
    plan: TripPlan,
    output_path: Path,
    *,
    canonical_plan: CanonicalTripPlan | None = None,
    report: UnfilledMappingReport | None = None,
) -> Path:
    """Fill a travel request spreadsheet template using trip plan data."""

    output_path = Path(output_path)
    output_path.write_bytes(
        render_travel_spreadsheet_bytes(plan, canonical_plan=canonical_plan, report=report)
    )
    return output_path


def _expense_from_receipt(receipt: Receipt) -> ExpenseItem:
    explanation = (
        "Third-party payment recorded on receipt." if receipt.paid_by_third_party else None
    )
    return ExpenseItem(
        category=ExpenseCategory.OTHER,
        description=f"Receipt from {receipt.vendor}",
        vendor=receipt.vendor,
        amount=receipt.total,
        expense_date=receipt.date,
        receipt_attached=True,
        receipt_url=receipt.file_reference,
        receipt_references=[receipt],
        third_party_paid_explanation=explanation,
    )


def _build_expense_report(plan: TripPlan, receipts: Sequence[Receipt]) -> ExpenseReport:
    expenses = [_expense_from_receipt(receipt) for receipt in receipts]
    return ExpenseReport(
        report_id=f"{plan.trip_id}-reconciliation",
        trip_id=plan.trip_id,
        traveler_name=plan.traveler_name,
        expenses=expenses,
    )


def reconcile(plan: TripPlan, receipts: list[Receipt]) -> ReconciliationResult:
    """Reconcile post-trip receipts against the planned costs."""

    report = _build_expense_report(plan, receipts)
    actual_total = report.total_amount()
    planned_total = plan.estimated_cost
    variance = actual_total - planned_total
    if variance > 0:
        status: ReconciliationStatus = "over_budget"
    elif variance < 0:
        status = "under_budget"
    else:
        status = "on_budget"
    return ReconciliationResult(
        trip_id=plan.trip_id,
        report_id=report.report_id,
        planned_total=planned_total,
        actual_total=actual_total,
        variance=variance,
        status=status,
        receipt_count=len(receipts),
        receipts_by_type=summarize_receipts(receipts),
        expenses_by_category=report.expenses_by_category(),
    )
