"""Stable policy API data contracts, independent of orchestration logic."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from .models import ApprovalEvent, ExceptionRequest, ExpenseCategory, TripStatus
from .validation import ValidationResult

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
_DOCUMENTATION_RULE_IDS = frozenset(
    {"fare_evidence", "hotel_comparison", "third_party_paid"}
)


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
    policy_version: str = Field(
        ..., description="Deterministic policy version identifier"
    )


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
    required_permission: str = Field(
        ..., description="Permission required to read the snapshot"
    )
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
    retryable: bool = Field(
        ..., description="Whether another retry should be attempted"
    )
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
    external_status: str = Field(
        ..., description="Transport or HTTP-style status summary"
    )
    poll_after_seconds: float | None = Field(
        default=None,
        ge=0,
        description="Suggested poll interval for non-terminal states",
    )
    updated_at: datetime | None = Field(
        default=None, description="When the execution state last changed"
    )


class PlannerProposalStatusPayload(BaseModel):
    """Canonical trip proposal status details carried by a poll response."""

    trip_id: str = Field(..., description="Trip identifier linked to the proposal")
    proposal_id: str = Field(..., description="Stable planner proposal identifier")
    proposal_version: str = Field(
        ..., description="Planner proposal version identifier"
    )
    execution_id: str = Field(
        ..., description="Execution identifier returned on submit"
    )
    status: TripStatus = Field(
        ..., description="Current canonical trip proposal status"
    )
    approval_history: tuple[ApprovalEvent, ...] = Field(
        default_factory=tuple,
        description="Immutable approval and override history for this proposal",
    )
    validation_results: list[ValidationResult] = Field(
        default_factory=list,
        description="Latest validation results attached to the proposal",
    )
    exception_requests: list[ExceptionRequest] = Field(
        default_factory=list,
        description="Current exception requests linked to the proposal",
    )


class PlannerProposalSubmissionRequest(BaseModel):
    """Planner-facing submission request contract for proposal execution."""

    trip_id: str = Field(..., description="Trip identifier linked to the proposal")
    proposal_id: str = Field(..., description="Stable planner proposal identifier")
    proposal_version: str = Field(
        ..., description="Planner proposal version identifier"
    )
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
    proposal_version: str = Field(
        ..., description="Planner proposal version identifier"
    )
    execution_id: str = Field(
        ..., description="Execution identifier returned on submit"
    )
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

    operation: PlannerOperationType = Field(
        ..., description="Operation that produced the response"
    )
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
    proposal_status: PlannerProposalStatusPayload | None = Field(
        default=None,
        description="Canonical status readback details when polling a stored proposal",
    )
    error: PlannerErrorRecord | None = Field(
        default=None, description="Structured error detail when the operation failed"
    )
    retry: PlannerRetryMetadata | None = Field(
        default=None,
        description="Retry guidance for non-terminal or unavailable states",
    )
    received_at: datetime = Field(..., description="When this response was produced")
    status_endpoint: str | None = Field(
        default=None, description="Stable endpoint for follow-up status checks"
    )


class PlannerProposalEvaluationRequest(BaseModel):
    """Planner-facing request for a deterministic evaluation result payload."""

    trip_id: str = Field(..., description="Trip identifier linked to the execution")
    proposal_id: str = Field(..., description="Stable planner proposal identifier")
    proposal_version: str = Field(
        ..., description="Planner proposal version identifier"
    )
    execution_id: str = Field(
        ..., description="Execution identifier returned on submit"
    )
    request_id: str | None = Field(
        default=None,
        description="Optional caller-supplied evaluation request identifier",
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
        default=False,
        description="Whether this effect prevents approval regardless of score",
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
        ...,
        description="Whether a hard policy constraint forced the final score to zero",
    )
    effects: list[PlannerPolicyScoreEffect] = Field(
        default_factory=list,
        description="Ordered hard-block, soft-penalty, and preference-tradeoff effects",
    )
    summary: str = Field(
        ..., description="Short explanation of the final scoring posture"
    )


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
    proposal_version: str = Field(
        ..., description="Planner proposal version identifier"
    )
    execution_id: str = Field(
        ..., description="Execution identifier returned on submit"
    )
    request_id: str = Field(..., description="Stable evaluation request identifier")
    correlation_id: PlannerCorrelationId = Field(
        ..., description="Correlation identifier shared across proposal operations"
    )
    outcome: PlannerEvaluationOutcome = Field(
        ..., description="Planner-facing evaluation outcome"
    )
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
        ...,
        description="How business policy constraints modified proposal preference scoring",
    )
    exception_requirements: list[PlannerExceptionRequirement] = Field(
        default_factory=list,
        description="Exception workflow requirements that remain in flight",
    )
    reoptimization_guidance: list[PlannerReoptimizationGuidance] = Field(
        default_factory=list,
        description="Deterministic follow-up guidance for the planner runtime",
    )
    generated_at: datetime = Field(
        ..., description="When this result payload was generated"
    )


class ReconciliationResult(BaseModel):
    """Summary of post-trip expense reconciliation."""

    trip_id: str = Field(..., description="Trip identifier")
    report_id: str = Field(..., description="Generated expense report identifier")
    planned_total: Decimal = Field(..., description="Estimated trip total")
    actual_total: Decimal = Field(..., description="Actual reconciled spend")
    variance: Decimal = Field(..., description="Actual minus planned spend variance")
    status: ReconciliationStatus = Field(
        ..., description="Budget reconciliation status"
    )
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


@dataclass(frozen=True)
class _MappedCellValue:
    cell: str
    value: object
    number_format: str | None = None
