"""Approval engine for evaluating expense reports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

from .config_loader import YamlConfigLoaderMixin, load_rules
from .models import (
    ApprovalDecision,
    ApprovalRule,
    ApprovalStatus,
    ExpenseItem,
    ExpenseReport,
)


def _default_rules_path() -> Path | None:
    """Return the default approval rules configuration path if present."""

    for parent in Path(__file__).resolve().parents:
        candidate = parent / "config" / "approval_rules.yaml"
        if candidate.exists():
            return candidate
    return None


def _package_rules_resource() -> resources.abc.Traversable | None:
    try:
        resource = resources.files("travel_plan_permission").joinpath(
            "config", "approval_rules.yaml"
        )
    except ModuleNotFoundError:
        return None
    return resource if resource.is_file() else None


@dataclass
class ApprovalEngine(YamlConfigLoaderMixin):
    """Evaluate expenses against configured approval rules."""

    rules: list[ApprovalRule]

    @classmethod
    def from_yaml(cls, content: str) -> ApprovalEngine:
        """Load approval rules from YAML content."""

        data = cls._load_yaml_mapping(content)
        raw_rules = data.get("rules")
        if not raw_rules:
            raise ValueError("Approval rules configuration must include a 'rules' list")
        return cls(load_rules(raw_rules, ApprovalRule.model_validate))

    @staticmethod
    def _default_config_path() -> Path | None:
        return _default_rules_path()

    @staticmethod
    def _read_default_config_resource() -> str | None:
        resource = _package_rules_resource()
        return resource.read_text(encoding="utf-8") if resource is not None else None

    @staticmethod
    def _missing_config_message() -> str:
        return "No approval rules file found"

    @classmethod
    def from_environment(cls, env_var: str = "APPROVAL_RULES") -> ApprovalEngine:
        """Load approval rules from an environment variable containing YAML."""

        return super().from_environment(env_var)

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
        elif all(decision.status == ApprovalStatus.AUTO_APPROVED for decision in decisions):
            report.approval_status = ApprovalStatus.AUTO_APPROVED
        else:
            report.approval_status = ApprovalStatus.PENDING

        return report
