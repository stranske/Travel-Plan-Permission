"""Core models for trip plans and expense reports."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel, Field

from .receipts import Receipt


class TripStatus(str, Enum):
    """Status of a trip plan."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"


class ExpenseCategory(str, Enum):
    """Categories for expense items."""

    AIRFARE = "airfare"
    LODGING = "lodging"
    GROUND_TRANSPORT = "ground_transport"
    MEALS = "meals"
    CONFERENCE_FEES = "conference_fees"
    OTHER = "other"


class ApprovalStatus(str, Enum):
    """Status of expense approval processing."""

    PENDING = "pending"
    AUTO_APPROVED = "auto_approved"
    FLAGGED = "flagged"


class ApprovalAction(str, Enum):
    """Action to take when a rule matches an expense."""

    AUTO_APPROVE = "auto_approve"
    REQUIRE_APPROVAL = "require_approval"


class ApprovalRule(BaseModel):
    """Approval rule for expense items."""

    name: str = Field(..., description="Unique rule name")
    threshold: Annotated[Decimal, Field(ge=0)] = Field(
        ..., description="Amount threshold that triggers the rule"
    )
    category: ExpenseCategory | None = Field(
        default=None, description="Optional category this rule applies to"
    )
    approver: str = Field(
        ..., description="Approver or role responsible for the decision"
    )
    action: ApprovalAction = Field(
        default=ApprovalAction.AUTO_APPROVE,
        description="Action to take when the rule matches",
    )

    def matches(self, expense: ExpenseItem) -> bool:
        """Return True when the rule applies to the expense category."""

        if self.category is None:
            return True
        return expense.category == self.category

    def evaluate(self, expense: ExpenseItem) -> ApprovalStatus | None:
        """Evaluate the expense against the rule and return a status when triggered."""

        if (
            self.action == ApprovalAction.AUTO_APPROVE
            and expense.amount <= self.threshold
        ):
            return ApprovalStatus.AUTO_APPROVED
        if (
            self.action == ApprovalAction.REQUIRE_APPROVAL
            and expense.amount >= self.threshold
        ):
            return ApprovalStatus.FLAGGED
        return None


class ApprovalDecision(BaseModel):
    """Result of evaluating an expense against the approval rules."""

    expense: ExpenseItem = Field(..., description="Expense evaluated")
    status: ApprovalStatus = Field(..., description="Outcome of the evaluation")
    rule_name: str = Field(
        ..., description="Name of the rule that triggered the decision"
    )
    approver: str = Field(..., description="Approver or role responsible")
    timestamp: datetime = Field(..., description="Time when the decision was made")
    reason: str | None = Field(
        default=None, description="Optional explanation for the decision"
    )


class ApprovalOutcome(str, Enum):
    """Outcome of an approval workflow decision."""

    APPROVED = "approved"
    REJECTED = "rejected"
    FLAGGED = "flagged"
    OVERRIDDEN = "overridden"


class ApprovalEvent(BaseModel):
    """Immutable audit record for a single approval or override decision."""

    approver_id: str = Field(..., description="Identifier of the approver or role")
    level: str = Field(..., description="Approval tier, e.g., manager or board")
    outcome: ApprovalOutcome = Field(
        ..., description="Result of the decision for the trip plan"
    )
    timestamp: datetime = Field(..., description="When the decision was recorded")
    justification: str | None = Field(
        default=None, description="Explanation required for overrides"
    )
    previous_status: TripStatus = Field(
        ..., description="Trip status before the decision was applied"
    )
    new_status: TripStatus = Field(
        ..., description="Trip status after the decision was applied"
    )

    model_config = {"frozen": True}

    def model_post_init(self, __context: object) -> None:
        if self.outcome == ApprovalOutcome.OVERRIDDEN and not self.justification:
            msg = "Override decisions require justification text"
            raise ValueError(msg)


class ExceptionType(str, Enum):
    """Exception categories aligned to policy-lite advisory rules."""

    ADVANCE_BOOKING = "advance_booking"
    DRIVING_VS_FLYING = "driving_vs_flying"
    HOTEL_COMPARISON = "hotel_comparison"
    LOCAL_OVERNIGHT = "local_overnight"
    MEAL_PER_DIEM = "meal_per_diem"

    @classmethod
    def from_policy_rule_id(cls, rule_id: str) -> ExceptionType:
        """Return the matching exception type for a policy-lite rule id."""

        try:
            return cls(rule_id)
        except ValueError as exc:
            msg = f"No exception type defined for policy rule '{rule_id}'"
            raise ValueError(msg) from exc


class ExceptionApprovalLevel(str, Enum):
    """Approval levels for exception routing."""

    MANAGER = "manager"
    DIRECTOR = "director"
    BOARD = "board"


class ExceptionStatus(str, Enum):
    """Lifecycle status for an exception request."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"


class ExceptionApprovalRecord(BaseModel):
    """Audit entry for an exception decision."""

    approver_id: str = Field(..., description="Identifier for the approver")
    level: ExceptionApprovalLevel = Field(
        ..., description="Approval level that handled the exception"
    )
    timestamp: datetime = Field(..., description="When the decision was recorded")
    notes: str | None = Field(
        default=None, description="Optional approver notes for the decision"
    )


def _approval_rank(level: ExceptionApprovalLevel) -> int:
    return list(ExceptionApprovalLevel).index(level)


def _next_level(level: ExceptionApprovalLevel) -> ExceptionApprovalLevel:
    ordered_levels = list(ExceptionApprovalLevel)
    index = ordered_levels.index(level)
    return ordered_levels[min(index + 1, len(ordered_levels) - 1)]


_BASE_EXCEPTION_LEVELS: dict[ExceptionType, ExceptionApprovalLevel] = {
    ExceptionType.ADVANCE_BOOKING: ExceptionApprovalLevel.MANAGER,
    ExceptionType.DRIVING_VS_FLYING: ExceptionApprovalLevel.MANAGER,
    ExceptionType.HOTEL_COMPARISON: ExceptionApprovalLevel.MANAGER,
    ExceptionType.LOCAL_OVERNIGHT: ExceptionApprovalLevel.DIRECTOR,
    ExceptionType.MEAL_PER_DIEM: ExceptionApprovalLevel.MANAGER,
}
_DIRECTOR_THRESHOLD = Decimal("5000")
_BOARD_THRESHOLD = Decimal("20000")
_ESCALATION_WINDOW = timedelta(hours=48)


def determine_exception_approval_level(
    exception_type: ExceptionType, amount: Decimal | None
) -> ExceptionApprovalLevel:
    """Determine the approval level based on type and amount."""

    level = _BASE_EXCEPTION_LEVELS[exception_type]

    if amount is not None:
        if amount >= _BOARD_THRESHOLD:
            level = max(level, ExceptionApprovalLevel.BOARD, key=_approval_rank)
        elif amount >= _DIRECTOR_THRESHOLD:
            level = max(level, ExceptionApprovalLevel.DIRECTOR, key=_approval_rank)
    return level


class ExceptionRequest(BaseModel):
    """Request to override an advisory policy-lite rule."""

    type: ExceptionType = Field(..., description="Exception category requested")
    justification: Annotated[
        str, Field(min_length=50, description="Reasoning for the exception")
    ] = Field(...)
    supporting_docs: list[str] = Field(
        default_factory=list,
        description="Optional supporting documentation references",
    )
    requestor: str = Field(..., description="Identifier of the person requesting")
    amount: Annotated[Decimal | None, Field(ge=0)] = Field(
        default=None, description="Financial impact of the exception"
    )
    approval_level: ExceptionApprovalLevel | None = Field(
        default=None,
        description="Routing level for the request; defaults based on type and amount",
    )
    status: ExceptionStatus = Field(
        default=ExceptionStatus.PENDING, description="Current status of the request"
    )
    approval: ExceptionApprovalRecord | None = Field(
        default=None, description="Recorded approval details when completed"
    )
    requested_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When the exception was submitted",
    )
    escalated_at: datetime | None = Field(
        default=None, description="Timestamp of the most recent escalation"
    )

    def model_post_init(self, __context: object) -> None:
        super().model_post_init(__context)
        if self.approval_level is None:
            self.approval_level = determine_exception_approval_level(
                self.type, self.amount
            )

    def approve(
        self,
        *,
        approver_id: str,
        level: ExceptionApprovalLevel | None = None,
        notes: str | None = None,
        timestamp: datetime | None = None,
    ) -> ExceptionApprovalRecord:
        """Mark the request as approved and record the decision."""

        decision_time = timestamp or datetime.now(UTC)
        approval_level = level or self.approval_level or ExceptionApprovalLevel.MANAGER
        self.approval = ExceptionApprovalRecord(
            approver_id=approver_id,
            level=approval_level,
            timestamp=decision_time,
            notes=notes,
        )
        self.status = ExceptionStatus.APPROVED
        self.approval_level = approval_level
        return self.approval

    def reject(self) -> None:
        """Mark the request as rejected."""

        self.status = ExceptionStatus.REJECTED

    def escalate_if_overdue(self, *, reference_time: datetime | None = None) -> bool:
        """Escalate pending requests that exceed the SLA window."""

        if self.status not in (ExceptionStatus.PENDING, ExceptionStatus.ESCALATED):
            return False

        now = reference_time or datetime.now(UTC)
        anchor = self.escalated_at or self.requested_at
        if now - anchor < _ESCALATION_WINDOW:
            return False

        self.status = ExceptionStatus.ESCALATED
        self.escalated_at = now
        self.approval_level = _next_level(
            self.approval_level or ExceptionApprovalLevel.MANAGER
        )
        return True


def build_exception_dashboard(
    requests: list[ExceptionRequest],
) -> dict[str, dict[str, int]]:
    """Aggregate exception patterns for reporting surfaces."""

    by_type = Counter()
    by_requestor = Counter()
    by_approver = Counter()

    for request in requests:
        by_type[request.type.value] += 1
        by_requestor[request.requestor] += 1
        if request.approval is not None:
            by_approver[request.approval.approver_id] += 1

    return {
        "by_type": dict(by_type),
        "by_requestor": dict(by_requestor),
        "by_approver": dict(by_approver),
    }


class TripPlan(BaseModel):
    """A trip plan request for approval."""

    trip_id: str = Field(..., description="Unique identifier for the trip")
    traveler_name: str = Field(..., description="Name of the traveler")
    destination: str = Field(..., description="Trip destination")
    departure_date: date = Field(..., description="Date of departure")
    return_date: date = Field(..., description="Date of return")
    purpose: str = Field(..., description="Business purpose of the trip")
    estimated_cost: Annotated[Decimal, Field(ge=0)] = Field(
        ..., description="Estimated total cost"
    )
    status: TripStatus = Field(default=TripStatus.DRAFT, description="Current status")
    expense_breakdown: dict[ExpenseCategory, Decimal] = Field(
        default_factory=dict,
        description="Optional planned spend by category",
    )
    selected_providers: dict[ExpenseCategory, str] = Field(
        default_factory=dict,
        description=(
            "Traveler-selected providers keyed by expense category; used for approved provider checks"
        ),
    )
    validation_results: list[ValidationResult] = Field(
        default_factory=list,
        description="Results from policy validation",
    )
    approval_history: tuple[ApprovalEvent, ...] = Field(
        default_factory=tuple,
        description="Append-only immutable audit log of approvals and overrides",
    )
    exception_requests: list[ExceptionRequest] = Field(
        default_factory=list,
        description="Exception requests tied to advisory policy rules",
    )

    def duration_days(self) -> int:
        """Calculate the duration of the trip in days."""
        return (self.return_date - self.departure_date).days + 1

    def run_validation(
        self,
        validator: PolicyValidator | None = None,
        *,
        reference_date: date | None = None,
    ) -> list[ValidationResult]:
        """Validate the trip plan against policy rules."""

        from .validation import (
            PolicyValidator,
        )  # Local import to avoid circular dependency

        engine = validator or PolicyValidator.from_file()
        results = engine.validate_plan(self, reference_date=reference_date)
        self.validation_results = results
        return results

    def record_approval_decision(
        self,
        *,
        approver_id: str,
        level: str,
        outcome: ApprovalOutcome,
        justification: str | None = None,
        timestamp: datetime | None = None,
        snapshot_store: ValidationSnapshotStore | None = None,
        validator: PolicyValidator | None = None,
    ) -> ApprovalEvent:
        """Append an immutable approval event and update trip status."""

        decision_time = timestamp or datetime.now(UTC)
        if outcome == ApprovalOutcome.OVERRIDDEN and not justification:
            msg = "Override decisions require justification text"
            raise ValueError(msg)

        new_status = self.status
        if outcome in (ApprovalOutcome.APPROVED, ApprovalOutcome.OVERRIDDEN):
            new_status = TripStatus.APPROVED
        elif outcome == ApprovalOutcome.REJECTED:
            new_status = TripStatus.REJECTED
        elif outcome == ApprovalOutcome.FLAGGED:
            new_status = TripStatus.SUBMITTED

        event = ApprovalEvent(
            approver_id=approver_id,
            level=level,
            outcome=outcome,
            timestamp=decision_time,
            justification=justification,
            previous_status=self.status,
            new_status=new_status,
        )

        self.approval_history = (*self.approval_history, event)
        self.status = new_status

        if snapshot_store is not None:
            validator = validator or PolicyValidator.from_file()
            results = self.validation_results or validator.validate_plan(self)
            self.validation_results = results
            policy_version = policy_version_hash(validator)
            previous_hash = snapshot_store.last_chain_hash(self.trip_id)
            snapshot = snapshot_from_plan(
                self,
                results=results,
                policy_version=policy_version,
                previous_hash=previous_hash,
            )
            snapshot_store.append(snapshot)
        return event

    def add_exception_request(
        self, exception_request: ExceptionRequest
    ) -> ExceptionRequest:
        """Attach an exception request to the trip plan."""

        self.exception_requests.append(exception_request)
        return exception_request


from .snapshots import (  # noqa: E402
    ValidationSnapshotStore,
    policy_version_hash,
    snapshot_from_plan,
)
from .validation import PolicyValidator, ValidationResult  # noqa: E402

TripPlan.model_rebuild()

if TYPE_CHECKING:
    PolicyValidator = PolicyValidator
    ValidationResult = ValidationResult


class ExpenseItem(BaseModel):
    """A single expense item in an expense report."""

    category: ExpenseCategory = Field(..., description="Category of the expense")
    description: str = Field(..., description="Description of the expense")
    vendor: str | None = Field(
        default=None, description="Vendor or merchant associated with the expense"
    )
    amount: Annotated[Decimal, Field(ge=0)] = Field(..., description="Amount spent")
    expense_date: date = Field(..., description="Date of the expense")
    receipt_attached: bool = Field(
        default=False, description="Whether a receipt is attached"
    )
    receipt_url: str | None = Field(
        default=None,
        description=(
            "URL or path to the receipt attachment; will be converted to a signed link"
        ),
    )
    receipt_references: list[Receipt] = Field(
        default_factory=list,
        description="Attached receipts with OCR and validation metadata",
    )
    third_party_paid_explanation: str | None = Field(
        default=None,
        description="Required when a third party covered any part of this expense",
    )

    def reimbursable_amount(self) -> Decimal:
        """Return the reimbursable amount excluding third-party paid receipts."""

        if self.is_third_party_paid:
            return Decimal("0")
        return self.amount

    @property
    def is_third_party_paid(self) -> bool:
        """True when any attached receipt indicates third-party payment."""

        return any(receipt.paid_by_third_party for receipt in self.receipt_references)

    def model_post_init(self, __context: object) -> None:
        super().model_post_init(__context)
        if self.is_third_party_paid and not self.third_party_paid_explanation:
            msg = "third_party_paid_explanation is required when receipts are paid by a third party"
            raise ValueError(msg)


class ExpenseReport(BaseModel):
    """An expense report for reimbursement."""

    report_id: str = Field(..., description="Unique identifier for the report")
    trip_id: str = Field(..., description="Associated trip ID")
    traveler_name: str = Field(..., description="Name of the traveler")
    cost_center: str | None = Field(
        default=None, description="Cost center associated with the expense report"
    )
    expenses: list[ExpenseItem] = Field(
        default_factory=list, description="List of expenses"
    )
    approval_status: ApprovalStatus = Field(
        default=ApprovalStatus.PENDING, description="Status after approval evaluation"
    )
    approval_decisions: list[ApprovalDecision] = Field(
        default_factory=list, description="Decision log for each expense item"
    )
    submitted_date: date | None = Field(default=None, description="Date submitted")
    approved_date: date | None = Field(default=None, description="Date approved")

    def total_amount(self) -> Decimal:
        """Calculate the reimbursable total amount of all expenses."""
        return sum((e.reimbursable_amount() for e in self.expenses), Decimal("0"))

    def expenses_by_category(self) -> dict[ExpenseCategory, Decimal]:
        """Group expenses by category and sum amounts."""
        totals: dict[ExpenseCategory, Decimal] = {}
        for expense in self.expenses:
            totals[expense.category] = (
                totals.get(expense.category, Decimal("0")) + expense.amount
            )
        return totals
