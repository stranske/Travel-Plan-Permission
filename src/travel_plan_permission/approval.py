"""Approval engine for evaluating expense reports."""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml

from .models import (
    ApprovalDecision,
    ApprovalRule,
    ApprovalStatus,
    ExpenseItem,
    ExpenseReport,
)


def _load_rules(raw_rules: Iterable[dict[str, object]]) -> list[ApprovalRule]:
    """Convert raw rule dictionaries into validated ApprovalRule objects."""

    return [ApprovalRule.model_validate(rule) for rule in raw_rules]


def _default_rules_path() -> Path | None:
    """Return the default approval rules configuration path if present."""

    for parent in Path(__file__).resolve().parents:
        candidate = parent / "config" / "approval_rules.yaml"
        if candidate.exists():
            return candidate
    return None


@dataclass
class ApprovalEngine:
    """Evaluate expenses against configured approval rules."""

    rules: list[ApprovalRule]

    @classmethod
    def from_yaml(cls, content: str) -> ApprovalEngine:
        """Load approval rules from YAML content."""

        data = yaml.safe_load(content) or {}
        raw_rules = data.get("rules")
        if not raw_rules:
            raise ValueError("Approval rules configuration must include a 'rules' list")
        return cls(_load_rules(raw_rules))

    @classmethod
    def from_file(cls, path: str | Path | None = None) -> ApprovalEngine:
        """Load approval rules from a YAML file."""

        target_path = Path(path) if path is not None else _default_rules_path()

        if target_path is None:
            raise FileNotFoundError("No approval rules file found")

        content = target_path.read_text(encoding="utf-8")
        return cls.from_yaml(content)

    @classmethod
    def from_environment(cls, env_var: str = "APPROVAL_RULES") -> ApprovalEngine:
        """Load approval rules from an environment variable containing YAML."""

        content = os.getenv(env_var)
        if not content:
            raise ValueError(f"Environment variable '{env_var}' is not set or empty")
        return cls.from_yaml(content)

    def evaluate_expense(self, expense: ExpenseItem) -> ApprovalDecision:
        """Evaluate a single expense and return a decision."""

        timestamp = datetime.now(UTC)
        for rule in self.rules:
            if not rule.matches(expense):
                continue

            status = rule.evaluate(expense)
            if status is not None:
                return ApprovalDecision(
                    expense=expense,
                    status=status,
                    rule_name=rule.name,
                    approver=rule.approver,
                    timestamp=timestamp,
                    reason=(
                        f"Expense amount {expense.amount} triggered rule '{rule.name}'"
                        f" with threshold {rule.threshold}"
                    ),
                )

        return ApprovalDecision(
            expense=expense,
            status=ApprovalStatus.PENDING,
            rule_name="no_rule_triggered",
            approver="unassigned",
            timestamp=timestamp,
            reason="No approval rule triggered",
        )

    def evaluate_report(self, report: ExpenseReport) -> ExpenseReport:
        """Evaluate an entire expense report, updating and returning it."""

        decisions = [self.evaluate_expense(expense) for expense in report.expenses]
        report.approval_decisions = decisions

        # If there are no expenses, keep the report in a PENDING state.
        if not decisions:
            report.approval_status = ApprovalStatus.PENDING
            return report
        if any(decision.status == ApprovalStatus.FLAGGED for decision in decisions):
            report.approval_status = ApprovalStatus.FLAGGED
        elif all(
            decision.status == ApprovalStatus.AUTO_APPROVED for decision in decisions
        ):
            report.approval_status = ApprovalStatus.AUTO_APPROVED
        else:
            report.approval_status = ApprovalStatus.PENDING

        return report
