"""Tests for the approval engine."""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal

from travel_plan_permission.approval import ApprovalEngine
from travel_plan_permission.models import (
    ApprovalStatus,
    ExpenseCategory,
    ExpenseItem,
    ExpenseReport,
)


def test_load_rules_from_file() -> None:
    """ApprovalEngine should load configuration from YAML file."""

    engine = ApprovalEngine.from_file()

    assert len(engine.rules) >= 1
    assert engine.rules[0].name == "meals_manager_review"


def test_load_rules_from_environment() -> None:
    """Approval rules can be loaded from environment variables."""

    env_rules = """
rules:
  - name: env_default
    threshold: 50
    action: auto_approve
    approver: ops
"""
    os.environ["APPROVAL_RULES"] = env_rules
    engine = ApprovalEngine.from_environment()

    expense = ExpenseItem(
        category=ExpenseCategory.OTHER,
        description="USB cable",
        amount=Decimal("10.00"),
        expense_date=date(2025, 1, 1),
    )

    decision = engine.evaluate_expense(expense)
    assert decision.status == ApprovalStatus.AUTO_APPROVED
    os.environ.pop("APPROVAL_RULES", None)


def test_auto_approve_under_threshold() -> None:
    """Expenses under $100 are auto-approved by default rule."""

    engine = ApprovalEngine.from_file()
    expense = ExpenseItem(
        category=ExpenseCategory.AIRFARE,
        description="Shuttle",
        amount=Decimal("50.00"),
        expense_date=date(2025, 1, 1),
    )

    decision = engine.evaluate_expense(expense)
    assert decision.status == ApprovalStatus.AUTO_APPROVED
    assert decision.rule_name == "default_under_100"


def test_flag_over_5000_requires_manager() -> None:
    """Expenses over $5000 require manager approval and are flagged."""

    engine = ApprovalEngine.from_file()
    expense = ExpenseItem(
        category=ExpenseCategory.LODGING,
        description="Luxury suite",
        amount=Decimal("7500.00"),
        expense_date=date(2025, 1, 1),
    )

    decision = engine.evaluate_expense(expense)
    assert decision.status == ApprovalStatus.FLAGGED
    assert decision.rule_name == "high_amount_flag"
    assert decision.approver == "manager"


def test_category_specific_rule_overrides_default() -> None:
    """Category-specific rules can override default thresholds."""

    engine = ApprovalEngine.from_file()
    expense = ExpenseItem(
        category=ExpenseCategory.MEALS,
        description="Team dinner",
        amount=Decimal("350.00"),
        expense_date=date(2025, 1, 1),
    )

    decision = engine.evaluate_expense(expense)
    assert decision.status == ApprovalStatus.FLAGGED
    assert decision.rule_name == "meals_manager_review"


def test_decisions_logged_with_timestamp_and_rule() -> None:
    """Approval decisions should log timestamp and rule details."""

    engine = ApprovalEngine.from_file()
    report = ExpenseReport(
        report_id="EXP-LOG-001",
        trip_id="TRIP-LOG-001",
        traveler_name="Logger",
        expenses=[
            ExpenseItem(
                category=ExpenseCategory.AIRFARE,
                description="Flight",
                amount=Decimal("80.00"),
                expense_date=date(2025, 1, 1),
            )
        ],
    )

    evaluated = engine.evaluate_report(report)

    assert evaluated.approval_status == ApprovalStatus.AUTO_APPROVED
    assert len(evaluated.approval_decisions) == 1
    decision = evaluated.approval_decisions[0]
    assert decision.rule_name == "default_under_100"
    assert decision.timestamp.tzinfo is not None


def test_evaluate_report_handles_empty_expenses() -> None:
    """Empty reports should remain pending with no decisions."""

    engine = ApprovalEngine.from_file()
    report = ExpenseReport(
        report_id="EXP-EMPTY-001",
        trip_id="TRIP-EMPTY-001",
        traveler_name="No Expenses",
        expenses=[],
    )

    evaluated = engine.evaluate_report(report)

    assert evaluated.approval_status == ApprovalStatus.PENDING
    assert evaluated.approval_decisions == []


def test_evaluate_report_flags_when_any_expense_flagged() -> None:
    """Any flagged decision should mark the report as flagged."""

    engine = ApprovalEngine.from_file()
    report = ExpenseReport(
        report_id="EXP-MIXED-001",
        trip_id="TRIP-MIXED-001",
        traveler_name="Mixed Decisions",
        expenses=[
            ExpenseItem(
                category=ExpenseCategory.AIRFARE,
                description="Shuttle",
                amount=Decimal("45.00"),
                expense_date=date(2025, 1, 1),
            ),
            ExpenseItem(
                category=ExpenseCategory.LODGING,
                description="Luxury suite",
                amount=Decimal("7500.00"),
                expense_date=date(2025, 1, 2),
            ),
        ],
    )

    evaluated = engine.evaluate_report(report)

    assert evaluated.approval_status == ApprovalStatus.FLAGGED
    assert {decision.status for decision in evaluated.approval_decisions} == {
        ApprovalStatus.AUTO_APPROVED,
        ApprovalStatus.FLAGGED,
    }
