"""Core models for trip plans and expense reports."""

from __future__ import annotations

from datetime import UTC, date, datetime
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
    validation_results: list[ValidationResult] = Field(
        default_factory=list,
        description="Results from policy validation",
    )
    approval_history: tuple[ApprovalEvent, ...] = Field(
        default_factory=tuple,
        description="Append-only immutable audit log of approvals and overrides",
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
        snapshot_store: "ValidationSnapshotStore" | None = None,
        validator: "PolicyValidator" | None = None,
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


from .validation import PolicyValidator, ValidationResult  # noqa: E402
from .snapshots import (  # noqa: E402
    ValidationSnapshotStore,
    policy_version_hash,
    snapshot_from_plan,
)

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
