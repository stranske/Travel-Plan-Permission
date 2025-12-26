"""Stable policy API surface for orchestration integrations."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from .models import ExpenseCategory, ExpenseItem, ExpenseReport, TripPlan
from .policy import PolicyContext, PolicyEngine, PolicyResult, Severity
from .policy_versioning import PolicyVersion
from .providers import ProviderRegistry, ProviderType
from .receipts import Receipt, summarize_receipts

PolicyIssueSeverity = Literal["info", "warning", "error"]
PolicyCheckStatus = Literal["pass", "fail"]
ReconciliationStatus = Literal["under_budget", "on_budget", "over_budget"]

__all__ = [
    "PolicyIssueSeverity",
    "PolicyCheckStatus",
    "ReconciliationStatus",
    "PolicyIssue",
    "PolicyCheckResult",
    "ReconciliationResult",
    "check_trip_plan",
    "list_allowed_vendors",
    "reconcile",
]


class PolicyIssue(BaseModel):
    """Single policy rule violation or advisory."""

    code: str = Field(..., description="Stable policy rule code")
    message: str = Field(..., description="Human-readable policy message")
    severity: PolicyIssueSeverity = Field(..., description="Severity of the issue")
    context: dict[str, object] = Field(
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


def _policy_version(engine: PolicyEngine) -> str:
    rule_config = {"rules": engine.describe_rules()}
    version = PolicyVersion.from_config(None, rule_config)
    return version.config_hash


def _context_from_plan(plan: TripPlan) -> PolicyContext:
    return PolicyContext(
        departure_date=plan.departure_date,
        return_date=plan.return_date,
        driving_cost=plan.expense_breakdown.get(ExpenseCategory.GROUND_TRANSPORT),
        flight_cost=plan.expense_breakdown.get(ExpenseCategory.AIRFARE),
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
    return PolicyCheckResult(
        status=status, issues=issues, policy_version=_policy_version(engine)
    )


def list_allowed_vendors(plan: TripPlan) -> list[str]:
    """Return approved vendors for the trip destination."""

    registry = ProviderRegistry.from_file()
    destination = plan.destination
    reference_date = plan.departure_date
    providers = {
        provider.name
        for provider_type in ProviderType
        for provider in registry.lookup(
            provider_type, destination, reference_date=reference_date
        )
    }
    return sorted(providers, key=str.lower)


def _expense_from_receipt(receipt: Receipt) -> ExpenseItem:
    explanation = (
        "Third-party payment recorded on receipt."
        if receipt.paid_by_third_party
        else None
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
