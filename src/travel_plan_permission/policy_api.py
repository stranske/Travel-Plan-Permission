"""Stable policy API surface for orchestration integrations."""

from __future__ import annotations

import json
import re
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from importlib import resources
from io import BytesIO
from pathlib import Path
from typing import Literal

from openpyxl import load_workbook  # type: ignore[import-untyped]
from openpyxl.workbook import Workbook  # type: ignore[import-untyped]
from pydantic import BaseModel, Field

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
from .policy_versioning import PolicyVersion
from .providers import ProviderRegistry, ProviderType, provider_type_for_category
from .receipts import Receipt, summarize_receipts
from .security import (
    PLANNER_EVALUATION_RESULT_ENDPOINT,
    PLANNER_EXECUTION_STATUS_ENDPOINT,
    PLANNER_POLICY_SNAPSHOT_ENDPOINT,
)

PolicyIssueSeverity = Literal["info", "warning", "error"]
PolicyCheckStatus = Literal["pass", "fail"]
ReconciliationStatus = Literal["under_budget", "on_budget", "over_budget"]
PolicySnapshotFreshness = Literal["current", "stale", "invalidated"]
PlannerOperationType = Literal[
    "submit_proposal",
    "poll_execution_status",
    "get_evaluation_result",
]
PlannerProposalStatus = Literal["pending", "succeeded", "failed", "unavailable"]
PlannerTransportPattern = Literal["sync", "async", "deferred"]
PlannerEvaluationOutcome = Literal[
    "compliant",
    "non_compliant",
    "exception_required",
]
PlannerExecutionState = Literal[
    "accepted",
    "running",
    "succeeded",
    "failed",
    "deferred",
    "retry_scheduled",
    "cancelled",
]
PolicyIssueContextValue = str | int | float | bool | None
_PLANNER_POLICY_CONTRACT_VERSION = "2026-04-11"
_PLANNER_POLICY_TTL = timedelta(hours=24)
_DOCUMENTATION_RULE_IDS = frozenset({"fare_evidence", "hotel_comparison", "third_party_paid"})

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


class PlannerPolicySnapshotRequest(BaseModel):
    """Planner-facing request envelope for policy snapshot fetch."""

    trip_id: str = Field(..., description="Trip identifier for the snapshot request")
    requested_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When the planner requested the snapshot",
    )
    snapshot_generated_at: datetime | None = Field(
        default=None,
        description="Previous snapshot timestamp when re-evaluating freshness",
    )
    known_policy_version: str | None = Field(
        default=None,
        description="Policy version already cached by the planner, if any",
    )
    invalidate_reason: str | None = Field(
        default=None,
        description="Explicit invalidation reason when the cached snapshot is unusable",
    )


class PlannerPolicyRequirement(BaseModel):
    """Planner-facing requirement line item for booking or documentation rules."""

    code: str = Field(..., description="Stable rule identifier")
    summary: str = Field(..., description="Human-readable planner guidance")
    severity: PolicyIssueSeverity = Field(..., description="Planner-facing severity")


class PlannerApprovalTrigger(BaseModel):
    """Reason the planner should surface approval or waiver handling."""

    code: str = Field(..., description="Stable trigger identifier")
    summary: str = Field(..., description="Human-readable trigger summary")
    blocking: bool = Field(..., description="Whether the trigger blocks submission")
    source: Literal["policy_rule", "exception_request"] = Field(
        ..., description="Origin of the trigger"
    )


class PlannerAuthContract(BaseModel):
    """Authentication contract for the planner-facing policy snapshot seam."""

    endpoint: str = Field(..., description="Stable planner-facing endpoint identifier")
    required_permission: str = Field(..., description="Permission required to read the snapshot")
    auth_scheme: str = Field(..., description="Authentication scheme to use")
    supported_sso: list[str] = Field(
        default_factory=list,
        description="Supported SSO providers for bearer token acquisition",
    )


class PlannerVersionContract(BaseModel):
    """Versioning metadata needed by the planner cache and transport layer."""

    contract_version: str = Field(..., description="Version of the snapshot contract")
    policy_version: str = Field(..., description="Deterministic policy version hash")
    planner_known_policy_version: str | None = Field(
        default=None,
        description="Policy version supplied by the planner cache, if any",
    )
    compatible_with_planner_cache: bool = Field(
        ..., description="Whether the planner cache matches the current policy version"
    )
    etag: str = Field(..., description="Stable cache validator for the snapshot")


class PlannerPolicySnapshot(BaseModel):
    """Planner-facing snapshot response for policy metadata and runtime gating."""

    trip_id: str = Field(..., description="Trip identifier")
    freshness: PolicySnapshotFreshness = Field(
        ..., description="Freshness state for the snapshot payload"
    )
    generated_at: datetime = Field(..., description="When this snapshot was generated")
    expires_at: datetime = Field(..., description="When the snapshot becomes stale")
    invalidated_at: datetime | None = Field(
        default=None, description="When the snapshot was explicitly invalidated"
    )
    invalidation_reason: str | None = Field(
        default=None, description="Why the snapshot is invalidated"
    )
    policy_status: PolicyCheckStatus = Field(
        ..., description="Current blocking-policy pass/fail status"
    )
    booking_requirements: list[PlannerPolicyRequirement] = Field(
        default_factory=list,
        description="Booking-time requirements the planner should surface",
    )
    documentation_rules: list[PlannerPolicyRequirement] = Field(
        default_factory=list,
        description="Documentation rules the planner should enforce or request",
    )
    approval_triggers: list[PlannerApprovalTrigger] = Field(
        default_factory=list,
        description="Current triggers that require approval or a waiver workflow",
    )
    auth: PlannerAuthContract = Field(
        ..., description="Authentication guidance for this transport seam"
    )
    versioning: PlannerVersionContract = Field(
        ..., description="Versioning metadata for caching and compatibility"
    )


class PlannerCorrelationId(BaseModel):
    """Stable correlation identifier for planner-originated operations."""

    value: str = Field(..., description="Correlation identifier value")
    issued_by: str = Field(
        default="trip-planner", description="System that minted the correlation ID"
    )


class PlannerRetryMetadata(BaseModel):
    """Retry guidance for non-terminal planner-facing operations."""

    attempt: int = Field(..., ge=0, description="Current attempt count")
    max_attempts: int = Field(..., ge=1, description="Maximum retry attempts")
    retryable: bool = Field(..., description="Whether another retry should be attempted")
    backoff_seconds: float | None = Field(
        default=None, ge=0, description="Suggested delay before retrying"
    )
    next_retry_at: datetime | None = Field(
        default=None, description="Recommended timestamp for the next retry"
    )
    reason: str = Field(..., description="Human-readable retry reason")


class PlannerErrorRecord(BaseModel):
    """Structured error detail for failed or unavailable proposal work."""

    code: str = Field(..., description="Stable error code")
    message: str = Field(..., description="Human-readable error summary")
    category: str = Field(..., description="Broad error category")
    retryable: bool = Field(..., description="Whether retrying may succeed")
    details: dict[str, object] = Field(
        default_factory=dict, description="Additional structured error context"
    )


class PlannerProposalExecutionStatus(BaseModel):
    """Execution status surfaced to the planner transport seam."""

    state: PlannerExecutionState = Field(..., description="Current execution state")
    terminal: bool = Field(..., description="Whether the execution has finished")
    summary: str = Field(..., description="Human-readable execution summary")
    external_status: str = Field(..., description="Transport or HTTP-style status summary")
    poll_after_seconds: float | None = Field(
        default=None, ge=0, description="Suggested poll interval for non-terminal states"
    )
    updated_at: datetime | None = Field(
        default=None, description="When the execution state last changed"
    )


class PlannerProposalSubmissionRequest(BaseModel):
    """Planner-facing submission request contract for proposal execution."""

    trip_id: str = Field(..., description="Trip identifier linked to the proposal")
    proposal_id: str = Field(..., description="Stable planner proposal identifier")
    proposal_version: str = Field(..., description="Planner proposal version identifier")
    payload: dict[str, object] = Field(
        default_factory=dict, description="Planner proposal payload or envelope"
    )
    request_id: str | None = Field(
        default=None, description="Optional caller-supplied request identifier"
    )
    correlation_id: PlannerCorrelationId | None = Field(
        default=None, description="Optional caller-supplied correlation identifier"
    )
    transport_pattern: PlannerTransportPattern = Field(
        default="deferred", description="Expected transport pattern for execution"
    )
    organization_id: str | None = Field(
        default=None, description="Optional organization or tenant identifier"
    )
    submitted_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When the planner submitted the proposal",
    )
    service_available: bool = Field(
        default=True,
        description="Whether the planner-facing submission seam is currently available",
    )


class PlannerProposalStatusRequest(BaseModel):
    """Planner-facing polling request contract for proposal execution status."""

    trip_id: str = Field(..., description="Trip identifier linked to the execution")
    proposal_id: str = Field(..., description="Stable planner proposal identifier")
    proposal_version: str = Field(..., description="Planner proposal version identifier")
    execution_id: str = Field(..., description="Execution identifier returned on submit")
    request_id: str | None = Field(
        default=None, description="Optional caller-supplied poll request identifier"
    )
    correlation_id: PlannerCorrelationId | None = Field(
        default=None, description="Optional caller-supplied correlation identifier"
    )
    transport_pattern: PlannerTransportPattern = Field(
        default="deferred", description="Expected transport pattern for polling"
    )
    requested_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When the planner polled the execution status",
    )
    service_available: bool = Field(
        default=True,
        description="Whether the planner-facing status seam is currently available",
    )


class PlannerProposalOperationResponse(BaseModel):
    """Planner-facing response envelope for submission and polling operations."""

    operation: PlannerOperationType = Field(..., description="Operation that produced the response")
    submission_status: PlannerProposalStatus = Field(
        ..., description="Planner-friendly lifecycle status for the submission"
    )
    request_id: str = Field(..., description="Stable request identifier")
    correlation_id: PlannerCorrelationId = Field(
        ..., description="Correlation identifier shared across related operations"
    )
    transport_pattern: PlannerTransportPattern = Field(
        ..., description="Transport pattern used by the operation"
    )
    execution_status: PlannerProposalExecutionStatus | None = Field(
        default=None, description="Execution-state detail when an execution exists"
    )
    result_payload: dict[str, object] = Field(
        default_factory=dict, description="Structured linkage payload for the planner"
    )
    error: PlannerErrorRecord | None = Field(
        default=None, description="Structured error detail when the operation failed"
    )
    retry: PlannerRetryMetadata | None = Field(
        default=None, description="Retry guidance for non-terminal or unavailable states"
    )
    received_at: datetime = Field(..., description="When this response was produced")
    status_endpoint: str | None = Field(
        default=None, description="Stable endpoint for follow-up status checks"
    )


class PlannerProposalEvaluationRequest(BaseModel):
    """Planner-facing request for a deterministic evaluation result payload."""

    trip_id: str = Field(..., description="Trip identifier linked to the execution")
    proposal_id: str = Field(..., description="Stable planner proposal identifier")
    proposal_version: str = Field(..., description="Planner proposal version identifier")
    execution_id: str = Field(..., description="Execution identifier returned on submit")
    request_id: str | None = Field(
        default=None, description="Optional caller-supplied evaluation request identifier"
    )
    correlation_id: PlannerCorrelationId | None = Field(
        default=None, description="Optional caller-supplied correlation identifier"
    )
    requested_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When the planner requested the evaluation result",
    )


class PlannerBlockingIssue(BaseModel):
    """Blocking issue detail the planner should surface directly to the user."""

    code: str = Field(..., description="Stable blocking issue code")
    message: str = Field(..., description="Human-readable blocking issue summary")
    field_path: str | None = Field(
        default=None, description="Relevant planner field or payload path"
    )
    resolution: str = Field(..., description="Deterministic next step for remediation")


class PlannerPreferredAlternative(BaseModel):
    """Preferred alternative surfaced when the current proposal is non-compliant."""

    category: str = Field(..., description="Alternative category such as airfare")
    title: str = Field(..., description="Human-readable alternative label")
    rationale: str = Field(..., description="Why the alternative is preferred")
    suggested_value: str | None = Field(
        default=None, description="Suggested machine-readable replacement value"
    )


class PlannerPolicyScoreEffect(BaseModel):
    """Single policy or preference effect applied to proposal scoring."""

    code: str = Field(..., description="Stable policy or preference effect code")
    category: Literal["hard_block", "soft_penalty", "preference_tradeoff"] = Field(
        ..., description="How the effect changes proposal scoring"
    )
    score_delta: int = Field(
        ..., description="Deterministic score movement applied to the base score"
    )
    blocking: bool = Field(
        default=False, description="Whether this effect prevents approval regardless of score"
    )
    message: str = Field(..., description="Human-readable explanation for the effect")


class PlannerPolicyScoreExplanation(BaseModel):
    """Business-mode policy scoring explanation for planner proposal ranking."""

    base_preference_score: int = Field(
        ..., ge=0, le=100, description="Score before business policy effects"
    )
    final_preference_score: int = Field(
        ..., ge=0, le=100, description="Score after business policy effects"
    )
    hard_blocked: bool = Field(
        ..., description="Whether a hard policy constraint forced the final score to zero"
    )
    effects: list[PlannerPolicyScoreEffect] = Field(
        default_factory=list,
        description="Ordered hard-block, soft-penalty, and preference-tradeoff effects",
    )
    summary: str = Field(..., description="Short explanation of the final scoring posture")


class PlannerExceptionRequirement(BaseModel):
    """Exception workflow requirement the planner must track or display."""

    type: str = Field(..., description="Stable exception type identifier")
    status: str = Field(..., description="Current exception workflow status")
    approval_level: str | None = Field(
        default=None, description="Current approval level required for the exception"
    )
    summary: str = Field(..., description="Human-readable exception workflow summary")


class PlannerReoptimizationGuidance(BaseModel):
    """Structured reoptimization guidance for planner follow-up flows."""

    code: str = Field(..., description="Stable reoptimization guidance code")
    summary: str = Field(..., description="Human-readable guidance summary")
    actions: list[str] = Field(
        default_factory=list,
        description="Deterministic follow-up actions for the planner",
    )


class PlannerProposalEvaluationResult(BaseModel):
    """Planner-facing evaluation result contract for a proposal execution."""

    trip_id: str = Field(..., description="Trip identifier linked to the execution")
    proposal_id: str = Field(..., description="Stable planner proposal identifier")
    proposal_version: str = Field(..., description="Planner proposal version identifier")
    execution_id: str = Field(..., description="Execution identifier returned on submit")
    request_id: str = Field(..., description="Stable evaluation request identifier")
    correlation_id: PlannerCorrelationId = Field(
        ..., description="Correlation identifier shared across proposal operations"
    )
    outcome: PlannerEvaluationOutcome = Field(..., description="Planner-facing evaluation outcome")
    result_endpoint: str = Field(
        ..., description="Stable endpoint for re-fetching this evaluation result"
    )
    status_endpoint: str = Field(
        ..., description="Stable endpoint for the execution status linkage"
    )
    policy_result: PolicyCheckResult = Field(
        ..., description="Underlying policy evaluation snapshot for this proposal"
    )
    blocking_issues: list[PlannerBlockingIssue] = Field(
        default_factory=list,
        description="Blocking issues that must be resolved before success",
    )
    preferred_alternatives: list[PlannerPreferredAlternative] = Field(
        default_factory=list,
        description="Preferred alternatives surfaced for non-compliant results",
    )
    score_explanation: PlannerPolicyScoreExplanation = Field(
        ..., description="How business policy constraints modified proposal preference scoring"
    )
    exception_requirements: list[PlannerExceptionRequirement] = Field(
        default_factory=list,
        description="Exception workflow requirements that remain in flight",
    )
    reoptimization_guidance: list[PlannerReoptimizationGuidance] = Field(
        default_factory=list,
        description="Deterministic follow-up guidance for the planner runtime",
    )
    generated_at: datetime = Field(..., description="When this result payload was generated")


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
            "depart_date": (canonical_plan.depart_date if canonical_plan else plan.departure_date),
            "return_date": (canonical_plan.return_date if canonical_plan else plan.return_date),
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


def _planner_requirement(rule: dict[str, object]) -> PlannerPolicyRequirement:
    severity = str(rule.get("severity", Severity.INFO))
    return PlannerPolicyRequirement(
        code=str(rule["rule_id"]),
        summary=str(rule.get("description", "")),
        severity=(
            "error"
            if severity == Severity.BLOCKING
            else "warning"
            if severity == Severity.ADVISORY
            else "info"
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
