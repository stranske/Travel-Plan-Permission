"""Core models for trip plans and expense reports."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field


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
    approver: str = Field(..., description="Approver or role responsible for the decision")
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

        if self.action == ApprovalAction.AUTO_APPROVE and expense.amount <= self.threshold:
            return ApprovalStatus.AUTO_APPROVED
        if self.action == ApprovalAction.REQUIRE_APPROVAL and expense.amount >= self.threshold:
            return ApprovalStatus.FLAGGED
        return None


class ApprovalDecision(BaseModel):
    """Result of evaluating an expense against the approval rules."""

    expense: ExpenseItem = Field(..., description="Expense evaluated")
    status: ApprovalStatus = Field(..., description="Outcome of the evaluation")
    rule_name: str = Field(..., description="Name of the rule that triggered the decision")
    approver: str = Field(..., description="Approver or role responsible")
    timestamp: datetime = Field(..., description="Time when the decision was made")
    reason: str | None = Field(default=None, description="Optional explanation for the decision")


class TripPlan(BaseModel):
    """A trip plan request for approval."""

    trip_id: str = Field(..., description="Unique identifier for the trip")
    traveler_name: str = Field(..., description="Name of the traveler")
    destination: str = Field(..., description="Trip destination")
    departure_date: date = Field(..., description="Date of departure")
    return_date: date = Field(..., description="Date of return")
    purpose: str = Field(..., description="Business purpose of the trip")
    estimated_cost: Annotated[Decimal, Field(ge=0)] = Field(..., description="Estimated total cost")
    status: TripStatus = Field(default=TripStatus.DRAFT, description="Current status")

    def duration_days(self) -> int:
        """Calculate the duration of the trip in days."""
        return (self.return_date - self.departure_date).days + 1


class ExpenseItem(BaseModel):
    """A single expense item in an expense report."""

    category: ExpenseCategory = Field(..., description="Category of the expense")
    description: str = Field(..., description="Description of the expense")
    amount: Annotated[Decimal, Field(ge=0)] = Field(..., description="Amount spent")
    expense_date: date = Field(..., description="Date of the expense")
    receipt_attached: bool = Field(default=False, description="Whether a receipt is attached")


class ExpenseReport(BaseModel):
    """An expense report for reimbursement."""

    report_id: str = Field(..., description="Unique identifier for the report")
    trip_id: str = Field(..., description="Associated trip ID")
    traveler_name: str = Field(..., description="Name of the traveler")
    expenses: list[ExpenseItem] = Field(default_factory=list, description="List of expenses")
    approval_status: ApprovalStatus = Field(
        default=ApprovalStatus.PENDING, description="Status after approval evaluation"
    )
    approval_decisions: list[ApprovalDecision] = Field(
        default_factory=list, description="Decision log for each expense item"
    )
    submitted_date: date | None = Field(default=None, description="Date submitted")
    approved_date: date | None = Field(default=None, description="Date approved")

    def total_amount(self) -> Decimal:
        """Calculate the total amount of all expenses."""
        return sum((e.amount for e in self.expenses), Decimal("0"))

    def expenses_by_category(self) -> dict[ExpenseCategory, Decimal]:
        """Group expenses by category and sum amounts."""
        totals: dict[ExpenseCategory, Decimal] = {}
        for expense in self.expenses:
            totals[expense.category] = totals.get(expense.category, Decimal("0")) + expense.amount
        return totals
