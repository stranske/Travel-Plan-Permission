"""Stable policy API surface for orchestration integrations."""

from __future__ import annotations

import json
import re
import tempfile
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from importlib import resources
from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.workbook import Workbook

from .canonical import CanonicalTripPlan
from .mapping import TemplateMapping, load_template_mapping
from .models import (
    ExceptionRequest,
    ExpenseCategory,
    ExpenseItem,
    ExpenseReport,
    TripPlan,
    TripStatus,
)
from .policy import PolicyContext, PolicyEngine, PolicyResult, Severity
from .policy_contract_models import (
    _DOCUMENTATION_RULE_IDS,
    _PLANNER_POLICY_CONTRACT_VERSION,
    _PLANNER_POLICY_TTL,
    PlannerApprovalTrigger,
    PlannerAuthContract,
    PlannerBlockingIssue,
    PlannerCorrelationId,
    PlannerErrorRecord,
    PlannerEvaluationOutcome,
    PlannerExceptionRequirement,
    PlannerExecutionState,
    PlannerOperationType,
    PlannerPolicyRequirement,
    PlannerPolicyScoreEffect,
    PlannerPolicyScoreExplanation,
    PlannerPolicySnapshot,
    PlannerPolicySnapshotRequest,
    PlannerPreferredAlternative,
    PlannerProposalEvaluationRequest,
    PlannerProposalEvaluationResult,
    PlannerProposalExecutionStatus,
    PlannerProposalOperationResponse,
    PlannerProposalStatus,
    PlannerProposalStatusPayload,
    PlannerProposalStatusRequest,
    PlannerProposalSubmissionRequest,
    PlannerReoptimizationGuidance,
    PlannerRetryMetadata,
    PlannerTransportPattern,
    PlannerVersionContract,
    PolicyCheckResult,
    PolicyCheckStatus,
    PolicyIssue,
    PolicyIssueSeverity,
    PolicySnapshotFreshness,
    ReconciliationResult,
    ReconciliationStatus,
    UnfilledMappingEntry,
    UnfilledMappingReport,
    _MappedCellValue,
)
from .policy_versioning import PolicyVersion
from .providers import ProviderRegistry, ProviderType, provider_type_for_category
from .receipts import Receipt, summarize_receipts
from .security import (
    PLANNER_EVALUATION_RESULT_ENDPOINT,
    PLANNER_EXECUTION_STATUS_ENDPOINT,
    PLANNER_POLICY_SNAPSHOT_ENDPOINT,
)
from .validation import PolicyValidator, ValidationResult
from .workbook_ooxml import render_mapped_workbook
from .workbook_population import populate_travel_workbook

__all__ = [
    "PolicyIssueSeverity",
    "PolicyCheckStatus",
    "PolicySnapshotFreshness",
    "PlannerOperationType",
    "PlannerProposalStatus",
    "PlannerTransportPattern",
    "PlannerEvaluationOutcome",
    "PlannerExecutionState",
    "ReconciliationStatus",
    "PolicyIssue",
    "PolicyCheckResult",
    "PlannerPolicySnapshotRequest",
    "PlannerPolicyRequirement",
    "PlannerApprovalTrigger",
    "PlannerAuthContract",
    "PlannerVersionContract",
    "PlannerPolicySnapshot",
    "PlannerCorrelationId",
    "PlannerRetryMetadata",
    "PlannerErrorRecord",
    "PlannerProposalExecutionStatus",
    "PlannerProposalStatusPayload",
    "PlannerProposalSubmissionRequest",
    "PlannerProposalStatusRequest",
    "PlannerProposalEvaluationRequest",
    "PlannerProposalOperationResponse",
    "PlannerBlockingIssue",
    "PlannerPreferredAlternative",
    "PlannerPolicyScoreEffect",
    "PlannerPolicyScoreExplanation",
    "PlannerExceptionRequirement",
    "PlannerReoptimizationGuidance",
    "PlannerProposalEvaluationResult",
    "ReconciliationResult",
    "UnfilledMappingEntry",
    "UnfilledMappingReport",
    "TripPlan",
    "Receipt",
    "check_trip_plan",
    "fill_travel_spreadsheet",
    "get_evaluation_result",
    "get_policy_snapshot",
    "list_allowed_vendors",
    "poll_execution_status",
    "reconcile",
    "submit_proposal",
]


_TEMPLATE_FILENAME = "Travel_Itinerary_Form_Jan_1_2026_runtime.xlsx"
_CURRENCY_FIELDS = {
    "air_travel_airport_parking_cost",
    "air_travel_ground_transport_cost",
    "air_travel_mileage_cost",
    "airfare_cost_comparison",
    "event_registration_cost",
    "flight_pref_outbound.roundtrip_cost",
    "ground_transport.rental_cost",
    "ground_transport.rental_daily_rate",
    "ground_transport.rideshare_cost",
    "ground_transport.shuttle_cost",
    "lowest_cost_roundtrip",
    "parking_daily_rate",
    "parking_estimate",
    "hotel.nightly_rate",
    "comparable_hotels[0].nightly_rate",
    "comparable_hotels[1].nightly_rate",
}
_INTEGER_FIELDS = {"destination_zip"}
_DATE_FIELDS = {"depart_date", "return_date"}
_DATETIME_FIELDS = {
    "flight_pref_outbound.depart_time",
    "flight_pref_outbound.arrive_time",
    "flight_pref_return.depart_time",
    "flight_pref_return.arrive_time",
}
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
    depart_date = canonical_plan.depart_date if canonical_plan else plan.departure_date
    return_date = canonical_plan.return_date if canonical_plan else plan.return_date
    valid_trip_dates = isinstance(depart_date, date) and isinstance(return_date, date)
    trip_nights = max((return_date - depart_date).days, 1) if valid_trip_dates else 1
    ground_transport_pref = (
        canonical_plan.ground_transport_pref if canonical_plan is not None else None
    )
    normalized_ground_transport = (
        ground_transport_pref.strip().casefold().replace("-", " ").replace("/", " ")
        if ground_transport_pref
        else ""
    )
    ground_transport_estimate = (
        canonical_plan.ground_transport_estimate
        if canonical_plan is not None
        else plan.expense_breakdown.get(ExpenseCategory.GROUND_TRANSPORT)
    )
    parking_estimate = (
        canonical_plan.parking_estimate
        if canonical_plan is not None
        else _expected_cost_value(plan, "airport_parking", "parking_estimate")
    )
    selected_airfare = (
        canonical_plan.flight_pref_outbound.roundtrip_cost
        if canonical_plan is not None
        and canonical_plan.flight_pref_outbound is not None
        and canonical_plan.flight_pref_outbound.roundtrip_cost is not None
        else plan.expense_breakdown.get(ExpenseCategory.AIRFARE)
    )
    lowest_airfare = (
        canonical_plan.lowest_cost_roundtrip if canonical_plan is not None else plan.lowest_fare
    )
    default_meal_count = trip_nights
    canonical_meal_counts = canonical_plan.meal_counts if canonical_plan is not None else None
    comparable_hotels = canonical_plan.comparable_hotels if canonical_plan is not None else None
    canonical_ground = canonical_plan.ground_transport if canonical_plan is not None else None

    def ground_choice(*terms: str) -> bool:
        return bool(normalized_ground_transport) and any(
            term in normalized_ground_transport for term in terms
        )

    rideshare_planned = (
        canonical_ground.rideshare_planned
        if canonical_ground is not None and canonical_ground.rideshare_planned is not None
        else ground_choice("rideshare", "taxi")
    )
    shuttle_planned = (
        canonical_ground.shuttle_planned
        if canonical_ground is not None and canonical_ground.shuttle_planned is not None
        else ground_choice("shuttle")
    )
    rental_planned = (
        canonical_ground.rental_planned
        if canonical_ground is not None and canonical_ground.rental_planned is not None
        else ground_choice("rental")
    )
    mileage_planned = (
        canonical_ground.mileage_planned
        if canonical_ground is not None and canonical_ground.mileage_planned is not None
        else ground_choice("personal", "mileage")
    )
    mosers_vehicle_planned = (
        canonical_ground.mosers_vehicle_planned
        if canonical_ground is not None and canonical_ground.mosers_vehicle_planned is not None
        else ground_choice("mosers", "organization vehicle")
    )
    mileage_miles = canonical_ground.mileage_miles if canonical_ground is not None else None
    mileage_cost = canonical_ground.mileage_cost if canonical_ground is not None else None
    if mileage_cost is None and mileage_miles is not None:
        # The supplied 2026 organizational workbook fixes its calculator at $0.725/mile.
        mileage_cost = mileage_miles * Decimal("0.725")
    rideshare_cost = canonical_ground.rideshare_cost if canonical_ground is not None else None
    shuttle_cost = canonical_ground.shuttle_cost if canonical_ground is not None else None
    rental_cost = canonical_ground.rental_cost if canonical_ground is not None else None
    if rideshare_planned and rideshare_cost is None:
        rideshare_cost = ground_transport_estimate
    if shuttle_planned and shuttle_cost is None:
        shuttle_cost = ground_transport_estimate
    if rental_planned and rental_cost is None:
        rental_cost = ground_transport_estimate
    destination_ground_cost = sum(
        (amount for amount in (rideshare_cost, shuttle_cost, rental_cost) if amount is not None),
        Decimal("0"),
    )
    if destination_ground_cost == 0 and ground_transport_estimate is not None:
        destination_ground_cost = ground_transport_estimate

    fields.update(
        {
            "traveler_name": (
                canonical_plan.traveler_name if canonical_plan else plan.traveler_name
            ),
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
            "event_dates": (
                canonical_plan.event_dates
                if canonical_plan is not None and canonical_plan.event_dates
                else (
                    f"{depart_date:%m/%d/%Y} - {return_date:%m/%d/%Y}" if valid_trip_dates else None
                )
            ),
            "departure_city_airport": (
                canonical_plan.departure_city_airport
                if canonical_plan is not None
                else plan.origin_city
            ),
            "return_city_airport": (
                canonical_plan.return_city_airport
                if canonical_plan is not None
                else plan.destination_city or city_state
            ),
            "depart_date": depart_date,
            "return_date": return_date,
            "event_registration_cost": (
                canonical_plan.event_registration_cost
                if canonical_plan and canonical_plan.event_registration_cost is not None
                else plan.expense_breakdown.get(ExpenseCategory.CONFERENCE_FEES)
            ),
            "flight_pref_outbound.roundtrip_cost": selected_airfare,
            "airfare_cost_comparison": selected_airfare,
            "lowest_cost_roundtrip": (
                canonical_plan.lowest_cost_roundtrip
                if canonical_plan and canonical_plan.lowest_cost_roundtrip is not None
                else plan.expense_breakdown.get(ExpenseCategory.AIRFARE)
            ),
            "parking_estimate": parking_estimate,
            "parking_daily_rate": (
                parking_estimate / Decimal(trip_nights) if parking_estimate is not None else None
            ),
            "airfare_within_threshold": (
                selected_airfare <= lowest_airfare + Decimal("200")
                if selected_airfare is not None and lowest_airfare is not None
                else None
            ),
            "hotel_comparison_reviewed": (
                bool(comparable_hotels) if comparable_hotels is not None else None
            ),
            "meal_counts.breakfast": (
                canonical_meal_counts.breakfast
                if canonical_meal_counts is not None
                else default_meal_count
            ),
            "meal_counts.lunch": (
                canonical_meal_counts.lunch
                if canonical_meal_counts is not None
                else default_meal_count
            ),
            "meal_counts.dinner": (
                canonical_meal_counts.dinner
                if canonical_meal_counts is not None
                else default_meal_count
            ),
            "ground_transport.mosers_vehicle_planned": mosers_vehicle_planned,
            "ground_transport.mileage_planned": mileage_planned,
            "ground_transport.mileage_miles": mileage_miles,
            "ground_transport.mileage_cost": mileage_cost,
            "ground_transport.rideshare_planned": rideshare_planned,
            "ground_transport.shuttle_planned": shuttle_planned,
            "ground_transport.rental_planned": rental_planned,
            "ground_transport.rideshare_cost": rideshare_cost,
            "ground_transport.shuttle_cost": shuttle_cost,
            "ground_transport.rental_cost": rental_cost,
            "ground_transport.rental_company": (
                canonical_ground.rental_company if canonical_ground is not None else None
            ),
            "ground_transport.rental_daily_rate": (
                canonical_ground.rental_daily_rate if canonical_ground is not None else None
            ),
            "ground_transport.rental_reason": (
                canonical_ground.rental_reason if canonical_ground is not None else None
            ),
            "air_travel_mileage_cost": mileage_cost,
            "air_travel_airport_parking_cost": parking_estimate,
            "air_travel_ground_transport_cost": destination_ground_cost or None,
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


def _format_date_value(value: object) -> date | None:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _format_datetime_value(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
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


def _policy_version(engine: PolicyEngine, validator: PolicyValidator | None = None) -> str:
    """Version the policy sources represented by a given API response."""

    rule_config: dict[str, object] = {"policy_lite_rules": engine.describe_rules()}
    if validator is not None:
        rule_config["validation_rules"] = [rule.model_dump(mode="json") for rule in validator.rules]
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
        context={"rule_id": result.rule_id, "severity": result.severity, "outcome": result.outcome},
    )


def _issue_from_validation_result(result: ValidationResult) -> PolicyIssue:
    """Translate validation.yaml violations into the planner's stable issue contract."""

    severity: PolicyIssueSeverity = result.severity.value
    return PolicyIssue(
        code=result.code,
        message=result.message,
        severity=severity,
        context={
            "rule_id": result.code,
            "rule_name": result.rule_name,
            "severity": result.severity.value,
            "source": "validation.yaml",
            "blocking": result.blocking,
        },
    )


def _planner_requirement(rule: dict[str, object]) -> PlannerPolicyRequirement:
    severity = str(rule.get("severity", Severity.INFO))
    return PlannerPolicyRequirement(
        code=str(rule["rule_id"]),
        summary=str(rule.get("description", "")),
        severity=(
            "error"
            if severity == Severity.BLOCKING
            else "warning" if severity == Severity.ADVISORY else "info"
        ),
    )


def _planner_freshness(
    request: PlannerPolicySnapshotRequest,
    *,
    generated_at: datetime,
    now: datetime,
) -> tuple[PolicySnapshotFreshness, datetime | None]:
    if request.invalidate_reason:
        return "invalidated", now
    if now > generated_at + _PLANNER_POLICY_TTL:
        return "stale", None
    return "current", None


def _coerce_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _planner_snapshot_etag(plan: TripPlan, *, policy_version: str) -> str:
    plan_payload = json.dumps(
        plan.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    plan_revision = sha256(plan_payload.encode("utf-8")).hexdigest()[:12]
    return f"{plan.trip_id}:{policy_version}:{_PLANNER_POLICY_CONTRACT_VERSION}:{plan_revision}"


def _stable_operation_id(prefix: str, *parts: str) -> str:
    seed = ":".join(parts)
    return f"{prefix}-{sha256(seed.encode('utf-8')).hexdigest()[:12]}"


def _proposal_request_id(
    operation: PlannerOperationType,
    *,
    trip_id: str,
    proposal_id: str,
    proposal_version: str,
    provided: str | None,
) -> str:
    if provided:
        return provided
    return _stable_operation_id("req", operation, trip_id, proposal_id, proposal_version)


def _proposal_correlation_id(
    *,
    trip_id: str,
    proposal_id: str,
    proposal_version: str,
    provided: PlannerCorrelationId | None,
) -> PlannerCorrelationId:
    if provided is not None:
        return provided
    return PlannerCorrelationId(
        value=_stable_operation_id("corr", trip_id, proposal_id, proposal_version)
    )


def _proposal_execution_id(*, trip_id: str, proposal_id: str, proposal_version: str) -> str:
    return _stable_operation_id("exec", trip_id, proposal_id, proposal_version)


def _proposal_status_endpoint(*, proposal_id: str, execution_id: str) -> str:
    return PLANNER_EXECUTION_STATUS_ENDPOINT.replace(":proposal_id", proposal_id).replace(
        ":execution_id", execution_id
    )


def _result_endpoint(*, execution_id: str) -> str:
    return PLANNER_EVALUATION_RESULT_ENDPOINT.replace(":execution_id", execution_id)


def _proposal_result_payload(
    *,
    trip_id: str,
    proposal_id: str,
    proposal_version: str,
    execution_id: str,
    queue_state: str,
) -> dict[str, object]:
    return {
        "trip_id": trip_id,
        "proposal_id": proposal_id,
        "proposal_version": proposal_version,
        "execution_id": execution_id,
        "queue_state": queue_state,
        "result_endpoint": _result_endpoint(execution_id=execution_id),
    }


def _proposal_status_payload(
    *,
    plan: TripPlan,
    proposal_id: str,
    proposal_version: str,
    execution_id: str,
) -> PlannerProposalStatusPayload:
    return PlannerProposalStatusPayload(
        trip_id=plan.trip_id,
        proposal_id=proposal_id,
        proposal_version=proposal_version,
        execution_id=execution_id,
        status=plan.status,
        approval_history=plan.approval_history,
        validation_results=plan.validation_results,
        exception_requests=plan.exception_requests,
    )


def _proposal_response_for_plan(
    *,
    operation: PlannerOperationType,
    plan: TripPlan,
    trip_id: str,
    proposal_id: str,
    proposal_version: str,
    transport_pattern: PlannerTransportPattern,
    service_available: bool,
    event_time: datetime,
    request_id: str,
    correlation_id: PlannerCorrelationId,
    organization_id: str | None = None,
) -> PlannerProposalOperationResponse:
    execution_id = _proposal_execution_id(
        trip_id=trip_id, proposal_id=proposal_id, proposal_version=proposal_version
    )
    status_endpoint = _proposal_status_endpoint(proposal_id=proposal_id, execution_id=execution_id)
    base_payload = _proposal_result_payload(
        trip_id=trip_id,
        proposal_id=proposal_id,
        proposal_version=proposal_version,
        execution_id=execution_id,
        queue_state="accepted",
    )
    if organization_id is not None:
        base_payload["organization_id"] = organization_id
    status_payload = (
        _proposal_status_payload(
            plan=plan,
            proposal_id=proposal_id,
            proposal_version=proposal_version,
            execution_id=execution_id,
        )
        if operation == "poll_execution_status"
        else None
    )

    if not service_available:
        return PlannerProposalOperationResponse(
            operation=operation,
            submission_status="unavailable",
            request_id=request_id,
            correlation_id=correlation_id,
            transport_pattern=transport_pattern,
            execution_status=None,
            result_payload=base_payload | {"queue_state": "unavailable"},
            error=PlannerErrorRecord(
                code="planner_transport_unavailable",
                message="Planner proposal transport is currently unavailable.",
                category="availability",
                retryable=True,
                details={"status_endpoint": status_endpoint},
            ),
            retry=PlannerRetryMetadata(
                attempt=0,
                max_attempts=5,
                retryable=True,
                backoff_seconds=60,
                next_retry_at=event_time + timedelta(seconds=60),
                reason="Planner transport is unavailable; retry after service recovery.",
            ),
            received_at=event_time,
            status_endpoint=status_endpoint,
            proposal_status=status_payload,
        )

    if plan.status == TripStatus.REJECTED:
        return PlannerProposalOperationResponse(
            operation=operation,
            submission_status="failed",
            request_id=request_id,
            correlation_id=correlation_id,
            transport_pattern=transport_pattern,
            execution_status=PlannerProposalExecutionStatus(
                state="failed",
                terminal=True,
                summary="Proposal execution failed policy review.",
                external_status="409 Conflict",
                updated_at=event_time,
            ),
            result_payload=base_payload | {"queue_state": "rejected"},
            error=PlannerErrorRecord(
                code="proposal_rejected",
                message="The proposal is currently in a rejected state and cannot proceed.",
                category="policy",
                retryable=False,
                details={"trip_status": str(plan.status)},
            ),
            received_at=event_time,
            status_endpoint=status_endpoint,
            proposal_status=status_payload,
        )

    if plan.status in {TripStatus.APPROVED, TripStatus.COMPLETED}:
        return PlannerProposalOperationResponse(
            operation=operation,
            submission_status="succeeded",
            request_id=request_id,
            correlation_id=correlation_id,
            transport_pattern=transport_pattern,
            execution_status=PlannerProposalExecutionStatus(
                state="succeeded",
                terminal=True,
                summary="Proposal execution completed successfully.",
                external_status="200 OK",
                updated_at=event_time,
            ),
            result_payload=base_payload | {"queue_state": "completed"},
            received_at=event_time,
            status_endpoint=status_endpoint,
            proposal_status=status_payload,
        )

    pending_state: PlannerExecutionState = "running" if transport_pattern == "async" else "deferred"
    queue_state = "running" if transport_pattern == "async" else "waiting_for_policy_engine"
    poll_after_seconds = 15.0 if transport_pattern == "async" else 30.0

    return PlannerProposalOperationResponse(
        operation=operation,
        submission_status="pending",
        request_id=request_id,
        correlation_id=correlation_id,
        transport_pattern=transport_pattern,
        execution_status=PlannerProposalExecutionStatus(
            state=pending_state,
            terminal=False,
            summary="Proposal queued for evaluation.",
            external_status="202 Accepted",
            poll_after_seconds=poll_after_seconds,
            updated_at=event_time,
        ),
        result_payload=base_payload | {"queue_state": queue_state},
        retry=PlannerRetryMetadata(
            attempt=0,
            max_attempts=5,
            retryable=True,
            backoff_seconds=poll_after_seconds,
            next_retry_at=event_time + timedelta(seconds=poll_after_seconds),
            reason="Await planner-side evaluation completion before retrying.",
        ),
        received_at=event_time,
        status_endpoint=status_endpoint,
        proposal_status=status_payload,
    )


def _blocking_issues(policy_result: PolicyCheckResult) -> list[PlannerBlockingIssue]:
    field_paths = {
        "fare_comparison": "selected_fare",
        "fare_evidence": "fare_evidence_attached",
        "hotel_comparison": "comparable_hotels",
        "third_party_paid": "third_party_payments",
    }
    resolutions = {
        "fare_comparison": "Choose a fare that meets the lowest-fare guidance or request an exception.",
        "fare_evidence": "Attach fare evidence before resubmitting the proposal.",
        "hotel_comparison": "Capture comparable hotel rates before resubmitting the proposal.",
        "third_party_paid": "Itemize third-party-paid amounts before resubmitting the proposal.",
    }
    return [
        PlannerBlockingIssue(
            code=issue.code,
            message=issue.message,
            field_path=field_paths.get(issue.code),
            resolution=resolutions.get(
                issue.code,
                "Update the proposal so the planner-facing policy rules pass.",
            ),
        )
        for issue in policy_result.issues
        if issue.severity == "error"
    ]


def _preferred_alternatives(plan: TripPlan) -> list[PlannerPreferredAlternative]:
    alternatives: list[PlannerPreferredAlternative] = []
    airfare_provider = plan.selected_providers.get(ExpenseCategory.AIRFARE)
    if (
        plan.selected_fare is not None
        and plan.lowest_fare is not None
        and plan.selected_fare > plan.lowest_fare
    ):
        provider_text = airfare_provider or "approved airfare option"
        alternatives.append(
            PlannerPreferredAlternative(
                category="airfare",
                title="Use the lower comparable airfare",
                rationale=(
                    f"Current airfare from {provider_text} exceeds the lowest comparable fare."
                ),
                suggested_value=str(plan.lowest_fare),
            )
        )
    if plan.comparable_hotels:
        lowest_hotel = min(plan.comparable_hotels)
        alternatives.append(
            PlannerPreferredAlternative(
                category="lodging",
                title="Use the lowest documented comparable hotel",
                rationale="The planner should favor the documented lower lodging alternative when available.",
                suggested_value=str(lowest_hotel),
            )
        )
    airfare_provider_type = provider_type_for_category(ExpenseCategory.AIRFARE.value)
    allowed_vendors = (
        _allowed_vendors_for_type(plan, airfare_provider_type)
        if airfare_provider_type is not None
        else []
    )
    airfare_allowed = [vendor for vendor in allowed_vendors if vendor != airfare_provider]
    if airfare_provider and airfare_allowed:
        alternatives.append(
            PlannerPreferredAlternative(
                category="provider",
                title="Use an approved contracted provider",
                rationale="A contracted provider is available for this route and should be preferred.",
                suggested_value=airfare_allowed[0],
            )
        )
    return alternatives


def _score_explanation(
    *,
    policy_result: PolicyCheckResult,
    preferred_alternatives: Sequence[PlannerPreferredAlternative],
) -> PlannerPolicyScoreExplanation:
    base_score = 100
    effects: list[PlannerPolicyScoreEffect] = []

    for issue in policy_result.issues:
        if issue.severity == "error":
            effects.append(
                PlannerPolicyScoreEffect(
                    code=issue.code,
                    category="hard_block",
                    score_delta=-base_score,
                    blocking=True,
                    message=(
                        f"Hard policy constraint '{issue.code}' blocks the proposal: "
                        f"{issue.message}"
                    ),
                )
            )
        elif issue.severity == "warning":
            effects.append(
                PlannerPolicyScoreEffect(
                    code=issue.code,
                    category="soft_penalty",
                    score_delta=-10,
                    blocking=False,
                    message=(
                        f"Soft policy constraint '{issue.code}' reduces preference score by 10: "
                        f"{issue.message}"
                    ),
                )
            )

    hard_blocked = any(effect.blocking for effect in effects)
    if not hard_blocked:
        for alternative in preferred_alternatives:
            effects.append(
                PlannerPolicyScoreEffect(
                    code=f"preference:{alternative.category}",
                    category="preference_tradeoff",
                    score_delta=-5,
                    blocking=False,
                    message=(
                        f"Preference tradeoff favors '{alternative.title}': {alternative.rationale}"
                    ),
                )
            )

    if hard_blocked:
        final_score = 0
        summary = "One or more hard policy constraints block the proposal; traveler preferences cannot override them."
    else:
        final_score = max(
            0,
            min(
                100,
                base_score + sum(effect.score_delta for effect in effects if not effect.blocking),
            ),
        )
        if any(effect.category == "soft_penalty" for effect in effects):
            summary = (
                "Soft policy constraints reduced the preference score without blocking submission."
            )
        elif effects:
            summary = "Preference tradeoffs changed the score while business policy still passed."
        else:
            summary = "Business policy did not modify the base preference score."

    return PlannerPolicyScoreExplanation(
        base_preference_score=base_score,
        final_preference_score=final_score,
        hard_blocked=hard_blocked,
        effects=effects,
        summary=summary,
    )


def _exception_requirements(
    exception_requests: Sequence[ExceptionRequest],
) -> list[PlannerExceptionRequirement]:
    requirements: list[PlannerExceptionRequirement] = []
    for request in exception_requests:
        if request.status.value == "approved":
            continue
        requirements.append(
            PlannerExceptionRequirement(
                type=request.type.value,
                status=request.status.value,
                approval_level=(
                    request.approval_level.value if request.approval_level is not None else None
                ),
                summary=(
                    f"{request.type.value.replace('_', ' ')} exception is "
                    f"{request.status.value.replace('_', ' ')}."
                ),
            )
        )
    return requirements


def _reoptimization_guidance(
    *,
    blocking_issues: Sequence[PlannerBlockingIssue],
    preferred_alternatives: Sequence[PlannerPreferredAlternative],
    exception_requirements: Sequence[PlannerExceptionRequirement],
) -> list[PlannerReoptimizationGuidance]:
    guidance: list[PlannerReoptimizationGuidance] = []
    issue_codes = {issue.code for issue in blocking_issues}
    if "fare_comparison" in issue_codes:
        guidance.append(
            PlannerReoptimizationGuidance(
                code="lower_trip_cost",
                summary="Reprice airfare and keep the selected fare within the lowest-fare threshold.",
                actions=[
                    "Refresh available airfare options.",
                    "Choose a fare that matches or improves on the lowest comparable fare.",
                ],
            )
        )
    if "fare_evidence" in issue_codes:
        guidance.append(
            PlannerReoptimizationGuidance(
                code="attach_fare_evidence",
                summary="Attach the supporting fare comparison before requesting evaluation again.",
                actions=[
                    "Upload the fare comparison artifact.",
                    "Persist the artifact reference in the proposal payload.",
                ],
            )
        )
    if preferred_alternatives:
        guidance.append(
            PlannerReoptimizationGuidance(
                code="apply_preferred_alternative",
                summary="Apply one of the published preferred alternatives before retrying evaluation.",
                actions=[alternative.title for alternative in preferred_alternatives],
            )
        )
    if exception_requirements:
        guidance.append(
            PlannerReoptimizationGuidance(
                code="route_exception_workflow",
                summary="Keep the proposal linked to an active exception workflow until approval completes.",
                actions=[requirement.summary for requirement in exception_requirements],
            )
        )
    return guidance


def _evaluation_outcome(
    *,
    plan: TripPlan,
    policy_result: PolicyCheckResult,
    exception_requirements: Sequence[PlannerExceptionRequirement],
) -> PlannerEvaluationOutcome:
    if exception_requirements:
        return "exception_required"
    if plan.status == TripStatus.REJECTED or any(
        issue.severity == "error" for issue in policy_result.issues
    ):
        return "non_compliant"
    return "compliant"


def get_policy_snapshot(
    plan: TripPlan,
    request: PlannerPolicySnapshotRequest | None = None,
) -> PlannerPolicySnapshot:
    """Build a planner-facing policy snapshot contract for a single trip."""

    request = request or PlannerPolicySnapshotRequest(trip_id=plan.trip_id)
    if request.trip_id != plan.trip_id:
        raise ValueError(
            "PlannerPolicySnapshotRequest.trip_id does not match plan.trip_id: "
            f"{request.trip_id!r} != {plan.trip_id!r}"
        )
    now = _coerce_utc(request.requested_at)
    freshness_generated_at = _coerce_utc(request.snapshot_generated_at or now)
    generated_at = now
    freshness, invalidated_at = _planner_freshness(
        request,
        generated_at=freshness_generated_at,
        now=now,
    )

    engine = PolicyEngine.from_file()
    context = _context_from_plan(plan)
    results = engine.validate(context)
    policy_version = _policy_version(engine)
    has_blocking = any(
        not result.passed and result.severity == Severity.BLOCKING for result in results
    )
    rule_metadata = engine.describe_rules()

    booking_requirements = [
        _planner_requirement(rule)
        for rule in rule_metadata
        if str(rule["rule_id"]) not in _DOCUMENTATION_RULE_IDS
    ]
    documentation_rules = [
        _planner_requirement(rule)
        for rule in rule_metadata
        if str(rule["rule_id"]) in _DOCUMENTATION_RULE_IDS
    ]
    approval_triggers = [
        PlannerApprovalTrigger(
            code=result.rule_id,
            summary=result.message,
            blocking=result.severity == Severity.BLOCKING,
            source="policy_rule",
        )
        for result in results
        if not result.passed
    ]
    approval_triggers.extend(
        PlannerApprovalTrigger(
            code=exception_request.type.value,
            summary=(
                f"Exception request for {exception_request.type.value.replace('_', ' ')} "
                f"is {exception_request.status.value}"
            ),
            blocking=exception_request.status.value != "approved",
            source="exception_request",
        )
        for exception_request in plan.exception_requests
    )

    return PlannerPolicySnapshot(
        trip_id=plan.trip_id,
        freshness=freshness,
        generated_at=generated_at,
        expires_at=generated_at + _PLANNER_POLICY_TTL,
        invalidated_at=invalidated_at,
        invalidation_reason=request.invalidate_reason,
        policy_status="fail" if has_blocking else "pass",
        booking_requirements=booking_requirements,
        documentation_rules=documentation_rules,
        approval_triggers=approval_triggers,
        auth=PlannerAuthContract(
            endpoint=PLANNER_POLICY_SNAPSHOT_ENDPOINT,
            required_permission="view",
            auth_scheme="Bearer token with SSO-backed access token",
            supported_sso=["azure_ad", "okta", "google"],
        ),
        versioning=PlannerVersionContract(
            contract_version=_PLANNER_POLICY_CONTRACT_VERSION,
            policy_version=policy_version,
            planner_known_policy_version=request.known_policy_version,
            compatible_with_planner_cache=request.known_policy_version in (None, policy_version),
            etag=_planner_snapshot_etag(plan, policy_version=policy_version),
        ),
    )


def submit_proposal(
    plan: TripPlan,
    request: PlannerProposalSubmissionRequest,
) -> PlannerProposalOperationResponse:
    """Build a planner-facing submission response for a proposal execution."""

    if request.trip_id != plan.trip_id:
        raise ValueError(
            "PlannerProposalSubmissionRequest.trip_id does not match plan.trip_id: "
            f"{request.trip_id!r} != {plan.trip_id!r}"
        )

    submitted_at = _coerce_utc(request.submitted_at)
    request_id = _proposal_request_id(
        "submit_proposal",
        trip_id=request.trip_id,
        proposal_id=request.proposal_id,
        proposal_version=request.proposal_version,
        provided=request.request_id,
    )
    correlation_id = _proposal_correlation_id(
        trip_id=request.trip_id,
        proposal_id=request.proposal_id,
        proposal_version=request.proposal_version,
        provided=request.correlation_id,
    )
    policy_result = check_trip_plan(plan)
    blocking_codes = [
        issue.code
        for issue in policy_result.issues
        if issue.severity == "error" and (issue.context or {}).get("blocking") is not False
    ]
    if (
        policy_result.status == "fail"
        and plan.status not in {TripStatus.REJECTED, TripStatus.APPROVED, TripStatus.COMPLETED}
    ):
        return PlannerProposalOperationResponse(
            operation="submit_proposal",
            submission_status="failed",
            request_id=request_id,
            correlation_id=correlation_id,
            transport_pattern=request.transport_pattern,
            execution_status=PlannerProposalExecutionStatus(
                state="failed",
                terminal=True,
                summary="Proposal submission blocked by the current policy verdict.",
                external_status="409 Conflict",
                updated_at=submitted_at,
            ),
            result_payload={
                **_proposal_result_payload(
                    trip_id=request.trip_id,
                    proposal_id=request.proposal_id,
                    proposal_version=request.proposal_version,
                    execution_id=_proposal_execution_id(
                        trip_id=request.trip_id,
                        proposal_id=request.proposal_id,
                        proposal_version=request.proposal_version,
                    ),
                    queue_state="blocked_by_policy",
                ),
                "blocking_codes": blocking_codes,
            },
            error=PlannerErrorRecord(
                code="proposal_blocked_by_policy",
                message="The proposal has blocking policy violations and cannot be submitted.",
                category="policy",
                retryable=False,
                details={"blocking_codes": blocking_codes},
            ),
            received_at=submitted_at,
            status_endpoint=_proposal_status_endpoint(
                proposal_id=request.proposal_id,
                execution_id=_proposal_execution_id(
                    trip_id=request.trip_id,
                    proposal_id=request.proposal_id,
                    proposal_version=request.proposal_version,
                ),
            ),
        )
    response = _proposal_response_for_plan(
        operation="submit_proposal",
        plan=plan,
        trip_id=request.trip_id,
        proposal_id=request.proposal_id,
        proposal_version=request.proposal_version,
        transport_pattern=request.transport_pattern,
        service_available=request.service_available,
        event_time=submitted_at,
        request_id=request_id,
        correlation_id=correlation_id,
        organization_id=request.organization_id,
    )
    if request.payload:
        response.result_payload["submitted_payload_keys"] = sorted(request.payload.keys())
    return response


def poll_execution_status(
    plan: TripPlan,
    request: PlannerProposalStatusRequest,
) -> PlannerProposalOperationResponse:
    """Build a planner-facing status response for a submitted proposal."""

    if request.trip_id != plan.trip_id:
        raise ValueError(
            "PlannerProposalStatusRequest.trip_id does not match plan.trip_id: "
            f"{request.trip_id!r} != {plan.trip_id!r}"
        )

    expected_execution_id = _proposal_execution_id(
        trip_id=request.trip_id,
        proposal_id=request.proposal_id,
        proposal_version=request.proposal_version,
    )
    if request.execution_id != expected_execution_id:
        raise ValueError(
            "PlannerProposalStatusRequest.execution_id does not match the stable "
            "execution identifier for this trip/proposal/version: "
            f"{request.execution_id!r} != {expected_execution_id!r}"
        )

    requested_at = _coerce_utc(request.requested_at)
    request_id = _proposal_request_id(
        "poll_execution_status",
        trip_id=request.trip_id,
        proposal_id=request.proposal_id,
        proposal_version=request.proposal_version,
        provided=request.request_id,
    )
    correlation_id = _proposal_correlation_id(
        trip_id=request.trip_id,
        proposal_id=request.proposal_id,
        proposal_version=request.proposal_version,
        provided=request.correlation_id,
    )
    return _proposal_response_for_plan(
        operation="poll_execution_status",
        plan=plan,
        trip_id=request.trip_id,
        proposal_id=request.proposal_id,
        proposal_version=request.proposal_version,
        transport_pattern=request.transport_pattern,
        service_available=request.service_available,
        event_time=requested_at,
        request_id=request_id,
        correlation_id=correlation_id,
    )


def get_evaluation_result(
    plan: TripPlan,
    request: PlannerProposalEvaluationRequest,
) -> PlannerProposalEvaluationResult:
    """Build the planner-facing evaluation-result contract for a proposal execution."""

    if request.trip_id != plan.trip_id:
        raise ValueError(
            "PlannerProposalEvaluationRequest.trip_id does not match plan.trip_id: "
            f"{request.trip_id!r} != {plan.trip_id!r}"
        )

    expected_execution_id = _proposal_execution_id(
        trip_id=request.trip_id,
        proposal_id=request.proposal_id,
        proposal_version=request.proposal_version,
    )
    if request.execution_id != expected_execution_id:
        raise ValueError(
            "PlannerProposalEvaluationRequest.execution_id does not match the stable "
            "execution identifier for this trip/proposal/version: "
            f"{request.execution_id!r} != {expected_execution_id!r}"
        )

    requested_at = _coerce_utc(request.requested_at)
    request_id = _proposal_request_id(
        "get_evaluation_result",
        trip_id=request.trip_id,
        proposal_id=request.proposal_id,
        proposal_version=request.proposal_version,
        provided=request.request_id,
    )
    correlation_id = _proposal_correlation_id(
        trip_id=request.trip_id,
        proposal_id=request.proposal_id,
        proposal_version=request.proposal_version,
        provided=request.correlation_id,
    )
    policy_result = check_trip_plan(plan)
    blocking_issues = _blocking_issues(policy_result)
    preferred_alternatives = _preferred_alternatives(plan)
    score_explanation = _score_explanation(
        policy_result=policy_result,
        preferred_alternatives=preferred_alternatives,
    )
    exception_requirements = _exception_requirements(plan.exception_requests)
    return PlannerProposalEvaluationResult(
        trip_id=request.trip_id,
        proposal_id=request.proposal_id,
        proposal_version=request.proposal_version,
        execution_id=request.execution_id,
        request_id=request_id,
        correlation_id=correlation_id,
        outcome=_evaluation_outcome(
            plan=plan,
            policy_result=policy_result,
            exception_requirements=exception_requirements,
        ),
        result_endpoint=_result_endpoint(execution_id=request.execution_id),
        status_endpoint=_proposal_status_endpoint(
            proposal_id=request.proposal_id,
            execution_id=request.execution_id,
        ),
        policy_result=policy_result,
        blocking_issues=blocking_issues,
        preferred_alternatives=preferred_alternatives,
        score_explanation=score_explanation,
        exception_requirements=exception_requirements,
        reoptimization_guidance=_reoptimization_guidance(
            blocking_issues=blocking_issues,
            preferred_alternatives=preferred_alternatives,
            exception_requirements=exception_requirements,
        ),
        generated_at=requested_at,
    )


def check_trip_plan(plan: TripPlan) -> PolicyCheckResult:
    """Evaluate both policy.yaml and validation.yaml for the planner verdict.

    ``policy.yaml`` supplies planner-facing guidance while ``validation.yaml``
    supplies organization-wide validation controls.  A blocking violation from
    either source fails the verdict and is returned through the same issue
    contract so downstream planner consumers cannot silently ignore it.
    """

    engine = PolicyEngine.from_file()
    validator = PolicyValidator.from_file()
    context = _context_from_plan(plan)
    policy_results = engine.validate(context)
    validation_results = validator.validate_plan(plan)
    issues = [
        *[_issue_from_result(result) for result in policy_results if not result.passed],
        *[_issue_from_validation_result(result) for result in validation_results],
    ]
    has_blocking = any(
        not result.passed and result.severity == Severity.BLOCKING for result in policy_results
    ) or any(result.is_blocking for result in validation_results)
    status: PolicyCheckStatus = "fail" if has_blocking else "pass"
    return PolicyCheckResult(
        status=status,
        issues=issues,
        policy_version=_policy_version(engine, validator),
    )


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


def _allowed_vendors_for_type(plan: TripPlan, provider_type: ProviderType) -> list[str]:
    """Return approved vendors for one provider category."""

    registry = ProviderRegistry.from_file()
    destination = plan.destination
    reference_date = plan.departure_date
    providers = {
        provider.name
        for provider in registry.lookup(provider_type, destination, reference_date=reference_date)
    }
    return sorted(providers, key=str.lower)


def _mapped_cell_values(
    plan: TripPlan,
    mapping: TemplateMapping,
    *,
    canonical_plan: CanonicalTripPlan | None = None,
    report: UnfilledMappingReport | None = None,
) -> list[_MappedCellValue]:
    """Resolve and normalize every writable mapping entry once."""

    mapped_values: list[_MappedCellValue] = []
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
            mapped_values.append(
                _MappedCellValue(cell=cell, value=amount, number_format=_CURRENCY_FORMAT)
            )
            continue
        if field_name in _INTEGER_FIELDS:
            try:
                numeric_value = int(str(value))
            except (TypeError, ValueError):
                if report is not None:
                    report.add("cells", field_name, cell, "invalid_integer")
                continue
            mapped_values.append(_MappedCellValue(cell=cell, value=numeric_value))
            continue
        if field_name in _DATETIME_FIELDS:
            formatted_datetime = _format_datetime_value(value)
            if formatted_datetime is None:
                if report is not None:
                    report.add("cells", field_name, cell, "invalid_datetime")
                continue
            mapped_values.append(_MappedCellValue(cell=cell, value=formatted_datetime))
            continue
        if field_name in _DATE_FIELDS or isinstance(value, date):
            formatted = _format_date_value(value)
            if formatted is None:
                if report is not None:
                    report.add("cells", field_name, cell, "invalid_date")
                continue
            mapped_values.append(_MappedCellValue(cell=cell, value=formatted))
            continue
        mapped_values.append(_MappedCellValue(cell=cell, value=value))

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
            mapped_values.append(
                _MappedCellValue(
                    cell=dropdown_cell,
                    value=_normalize_dropdown_value(value, options),
                )
            )

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
        mapped_values.append(
            _MappedCellValue(
                cell=checkbox_cell,
                value=true_value if bool(value) else false_value,
            )
        )

    return mapped_values


def _populate_travel_workbook(
    wb: Workbook,
    plan: TripPlan,
    mapping: TemplateMapping,
    *,
    canonical_plan: CanonicalTripPlan | None = None,
    report: UnfilledMappingReport | None = None,
) -> None:
    populate_travel_workbook(
        wb,
        plan,
        mapping,
        canonical_plan=canonical_plan,
        report=report,
        mapped_cell_values=_mapped_cell_values,
    )


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
    if mapping.metadata.get("render_engine") == "ooxml":
        worksheet_name = mapping.metadata.get("worksheet")
        if not isinstance(worksheet_name, str):
            raise ValueError("OOXML template mappings must declare a worksheet name.")
        mapped_values = _mapped_cell_values(
            plan,
            mapping,
            canonical_plan=canonical_plan,
            report=report,
        )
        cell_formulas = {
            formula_cell: formula_value
            for formula_config in mapping.formulas.values()
            if isinstance((formula_cell := formula_config.get("cell")), str)
            and isinstance((formula_value := formula_config.get("formula")), str)
        }
        return render_mapped_workbook(
            template_bytes,
            worksheet_name=worksheet_name,
            cell_values={entry.cell: entry.value for entry in mapped_values},
            cell_formulas=cell_formulas,
        )

    wb = load_workbook(BytesIO(template_bytes))
    _populate_travel_workbook(
        wb,
        plan,
        mapping,
        canonical_plan=canonical_plan,
        report=report,
    )
    wb.calculation.calcMode = "auto"
    wb.calculation.fullCalcOnLoad = True
    wb.calculation.forceFullCalc = True
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
