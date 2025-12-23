"""Validation rules for trip plan business logic."""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Iterable, Literal, TYPE_CHECKING

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import ExpenseCategory

if TYPE_CHECKING:
    from .models import TripPlan


class ValidationSeverity(str, Enum):
    """Severity for validation results."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ValidationResult(BaseModel):
    """Outcome of running a validation rule."""

    code: str = Field(..., description="Stable validation code")
    message: str = Field(..., description="Human-readable explanation")
    severity: ValidationSeverity = Field(..., description="Severity level")
    rule_name: str = Field(..., description="Rule that produced the result")
    blocking: bool = Field(
        default=True,
        description="Whether the rule should prevent submission when violated",
    )

    @property
    def is_blocking(self) -> bool:
        """Return True when the result should block submission."""

        return self.blocking and self.severity == ValidationSeverity.ERROR


class ValidationRule(BaseModel):
    """Base class for validation rules."""

    name: str = Field(..., description="Unique rule name")
    code: str = Field(..., description="Stable validation code")
    severity: ValidationSeverity = Field(
        default=ValidationSeverity.ERROR, description="Severity of a violation"
    )
    blocking: bool = Field(
        default=True,
        description="Whether a violation prevents submission",
    )

    model_config = ConfigDict(extra="forbid")

    def evaluate(self, plan: TripPlan, *, reference_date: date | None = None) -> list[ValidationResult]:
        """Evaluate a plan and return any validation results."""

        raise NotImplementedError

    def _result(self, *, message: str) -> ValidationResult:
        return ValidationResult(
            code=self.code,
            message=message,
            severity=self.severity,
            rule_name=self.name,
            blocking=self.blocking,
        )


class AdvanceBookingRule(ValidationRule):
    """Ensure trips are booked with sufficient notice."""

    type: Literal["advance_booking"] = Field(
        default="advance_booking", description="Rule type discriminator"
    )
    min_days_domestic: int | None = Field(
        default=None, ge=0, description="Minimum days notice for domestic trips"
    )
    min_days_international: int | None = Field(
        default=None, ge=0, description="Minimum days notice for international trips"
    )
    international_destinations: list[str] = Field(
        default_factory=list,
        description="Destinations treated as international (case-insensitive substring match)",
    )

    def _is_international(self, plan: TripPlan) -> bool:
        destination_lower = plan.destination.lower()
        return any(keyword.lower() in destination_lower for keyword in self.international_destinations)

    def _required_notice(self, plan: TripPlan) -> int | None:
        if self._is_international(plan):
            return self.min_days_international
        return self.min_days_domestic

    def evaluate(self, plan: TripPlan, *, reference_date: date | None = None) -> list[ValidationResult]:
        today = reference_date or date.today()
        required_notice = self._required_notice(plan)
        if required_notice is None:
            return []

        notice_days = (plan.departure_date - today).days
        if notice_days < required_notice:
            return [
                self._result(
                    message=(
                        "Trips must be booked at least "
                        f"{required_notice} days in advance; only {notice_days} days provided"
                    )
                )
            ]
        return []


class BudgetLimitRule(ValidationRule):
    """Validate trip cost against configured limits."""

    type: Literal["budget_limit"] = Field(default="budget_limit", description="Rule type")
    trip_limit: Decimal | None = Field(
        default=None, ge=0, description="Maximum allowed estimated trip cost"
    )
    category_limits: dict[ExpenseCategory, Decimal] = Field(
        default_factory=dict, description="Maximum planned spend per category"
    )

    @field_validator("category_limits", mode="before")
    @classmethod
    def _coerce_category_keys(cls, value: object) -> dict[ExpenseCategory, Decimal]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise TypeError("category_limits must be a mapping")
        return {ExpenseCategory(key): Decimal(str(limit)) for key, limit in value.items()}

    def evaluate(self, plan: TripPlan, *, reference_date: date | None = None) -> list[ValidationResult]:
        results: list[ValidationResult] = []
        if self.trip_limit is not None and plan.estimated_cost > self.trip_limit:
            results.append(
                self._result(
                    message=(
                        f"Estimated cost {plan.estimated_cost} exceeds trip limit {self.trip_limit}"
                    )
                )
            )

        for category, limit in self.category_limits.items():
            planned_amount = plan.expense_breakdown.get(category, Decimal("0"))
            if planned_amount > limit:
                results.append(
                    self._result(
                        message=(
                            f"Planned {category.value} spend {planned_amount} exceeds limit {limit}"
                        )
                    )
                )
        return results


class DurationLimitRule(ValidationRule):
    """Restrict maximum consecutive travel days."""

    type: Literal["duration_limit"] = Field(default="duration_limit", description="Rule type")
    max_consecutive_days: int = Field(..., gt=0, description="Maximum allowed trip duration in days")

    def evaluate(self, plan: TripPlan, *, reference_date: date | None = None) -> list[ValidationResult]:
        duration = plan.duration_days()
        if duration > self.max_consecutive_days:
            return [
                self._result(
                    message=(
                        f"Trip duration {duration} days exceeds maximum of {self.max_consecutive_days}"
                    )
                )
            ]
        return []


_RULE_TYPES = {
    "advance_booking": AdvanceBookingRule,
    "budget_limit": BudgetLimitRule,
    "duration_limit": DurationLimitRule,
}


def _default_policy_path() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "config" / "policy.yaml"
        if candidate.exists():
            return candidate
    return None


def _load_rules(raw_rules: Iterable[dict[str, object]]) -> list[ValidationRule]:
    rules: list[ValidationRule] = []
    for raw_rule in raw_rules:
        rule_type = raw_rule.get("type")
        if not isinstance(rule_type, str):
            raise ValueError("Each rule must include a string 'type'")
        rule_cls = _RULE_TYPES.get(rule_type)
        if rule_cls is None:
            raise ValueError(f"Unsupported rule type: {rule_type}")
        rules.append(rule_cls.model_validate(raw_rule))
    return rules


class PolicyValidator:
    """Evaluate a trip plan against configured policy rules."""

    def __init__(self, rules: Iterable[ValidationRule]):
        self.rules = list(rules)

    @classmethod
    def from_yaml(cls, content: str) -> "PolicyValidator":
        data = yaml.safe_load(content) or {}
        raw_rules = data.get("rules")
        if not raw_rules:
            raise ValueError("Policy configuration must include a 'rules' list")
        return cls(_load_rules(raw_rules))

    @classmethod
    def from_file(cls, path: str | Path | None = None) -> "PolicyValidator":
        target_path = Path(path) if path is not None else _default_policy_path()
        if target_path is None:
            raise FileNotFoundError("No policy.yaml file found")
        return cls.from_yaml(target_path.read_text(encoding="utf-8"))

    @classmethod
    def from_environment(cls, env_var: str = "POLICY_CONFIG") -> "PolicyValidator":
        content = os.getenv(env_var)
        if not content:
            raise ValueError(f"Environment variable '{env_var}' is not set or empty")
        return cls.from_yaml(content)

    def validate_plan(self, plan: TripPlan, *, reference_date: date | None = None) -> list[ValidationResult]:
        results: list[ValidationResult] = []
        for rule in self.rules:
            results.extend(rule.evaluate(plan, reference_date=reference_date))
        return results

    def can_submit(self, plan: TripPlan, *, reference_date: date | None = None) -> bool:
        return not any(result.is_blocking for result in self.validate_plan(plan, reference_date=reference_date))
