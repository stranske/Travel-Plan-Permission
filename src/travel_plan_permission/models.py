"""Core models for trip plans and expense reports."""

from __future__ import annotations

from datetime import date
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

    def duration_days(self) -> int:
        """Calculate the duration of the trip in days."""
        return (self.return_date - self.departure_date).days + 1


class ExpenseItem(BaseModel):
    """A single expense item in an expense report."""

    category: ExpenseCategory = Field(..., description="Category of the expense")
    description: str = Field(..., description="Description of the expense")
    amount: Annotated[Decimal, Field(ge=0)] = Field(..., description="Amount spent")
    expense_date: date = Field(..., description="Date of the expense")
    receipt_attached: bool = Field(
        default=False, description="Whether a receipt is attached"
    )


class ExpenseReport(BaseModel):
    """An expense report for reimbursement."""

    report_id: str = Field(..., description="Unique identifier for the report")
    trip_id: str = Field(..., description="Associated trip ID")
    traveler_name: str = Field(..., description="Name of the traveler")
    expenses: list[ExpenseItem] = Field(
        default_factory=list, description="List of expenses"
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
            totals[expense.category] = (
                totals.get(expense.category, Decimal("0")) + expense.amount
            )
        return totals
