"""Policy-lite validation rules for trip plans and expenses.

This module implements a configurable policy engine that evaluates a trip plan
context against a set of rules. Each rule returns a structured result that
captures whether the rule passed, the severity (blocking vs advisory), and a
message that includes the relevant threshold or policy text.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import yaml

from .models import ExpenseItem


class Severity(str):
    """Severity of a policy result."""

    BLOCKING = "blocking"
    ADVISORY = "advisory"
    INFO = "info"


@dataclass
class PolicyResult:
    """Result of evaluating a single policy rule."""

    rule_id: str
    severity: str
    passed: bool
    message: str


@dataclass
class PolicyContext:
    """Input data used by the policy engine.

    The context intentionally stays lightweight and only includes the fields
    needed by the policy-lite rules. All attributes are optional so callers can
    gradually adopt the rules without breaking existing flows.
    """

    booking_date: date | None = None
    departure_date: date | None = None
    return_date: date | None = None
    selected_fare: Decimal | None = None
    lowest_fare: Decimal | None = None
    cabin_class: str | None = None
    flight_duration_hours: float | None = None
    fare_evidence_attached: bool | None = None
    driving_cost: Decimal | None = None
    flight_cost: Decimal | None = None
    comparable_hotels: list[Decimal] | None = None
    distance_from_office_miles: float | None = None
    overnight_stay: bool | None = None
    meals_provided: bool | None = None
    meal_per_diem_requested: bool | None = None
    expenses: list[ExpenseItem] | None = None

    # Third-party paid entries should be itemized to exclude them from
    # reimbursement.
    third_party_payments: list[dict[str, object]] | None = None


class PolicyRule(ABC):
    """Base class for all policy-lite rules."""

    rule_id: str
    severity: str

    def __init__(self, severity: str) -> None:
        self.severity = severity

    @abstractmethod
    def evaluate(self, context: PolicyContext) -> PolicyResult:
        """Evaluate the rule and return a structured result."""

    @abstractmethod
    def message(self) -> str:
        """Return the policy message associated with the rule."""

    def _result(self, passed: bool, message: str | None = None) -> PolicyResult:
        return PolicyResult(
            rule_id=self.rule_id,
            severity=self.severity if not passed else Severity.INFO,
            passed=passed,
            message=message or self.message(),
        )


class AdvanceBookingRule(PolicyRule):
    rule_id = "advance_booking"

    def __init__(self, days_required: int, severity: str) -> None:
        super().__init__(severity)
        self.days_required = days_required

    def evaluate(self, context: PolicyContext) -> PolicyResult:
        if context.booking_date is None or context.departure_date is None:
            return self._result(
                True, "Advance booking check skipped due to missing dates"
            )

        days_notice = (context.departure_date - context.booking_date).days
        if days_notice < self.days_required:
            return self._result(
                False,
                f"Bookings should be made at least {self.days_required} days in advance; only {days_notice} days provided.",
            )
        return self._result(
            True,
            f"Booked {days_notice} days in advance (minimum {self.days_required}).",
        )

    def message(self) -> str:  # pragma: no cover - static template
        return f"Bookings must be made {self.days_required} days before departure."


class FareComparisonRule(PolicyRule):
    rule_id = "fare_comparison"

    def __init__(self, max_over_lowest: Decimal, severity: str) -> None:
        super().__init__(severity)
        self.max_over_lowest = Decimal(max_over_lowest)

    def evaluate(self, context: PolicyContext) -> PolicyResult:
        if context.selected_fare is None or context.lowest_fare is None:
            return self._result(
                True, "Fare comparison skipped due to missing fare data"
            )

        overage = context.selected_fare - context.lowest_fare
        if overage > self.max_over_lowest:
            return self._result(
                False,
                (
                    f"Selected fare exceeds lowest available by {overage} which is above the {self.max_over_lowest}"
                    " allowable threshold."
                ),
            )
        return self._result(
            True, f"Fare within {self.max_over_lowest} of lowest available."
        )

    def message(self) -> str:  # pragma: no cover - static template
        return f"Selected fare must be within {self.max_over_lowest} of the lowest available option."


class CabinClassRule(PolicyRule):
    rule_id = "cabin_class"

    def __init__(
        self, long_haul_hours: float, allowed_classes: Iterable[str], severity: str
    ) -> None:
        super().__init__(severity)
        self.long_haul_hours = float(long_haul_hours)
        self.allowed_classes = {c.lower() for c in allowed_classes}

    def evaluate(self, context: PolicyContext) -> PolicyResult:
        if context.cabin_class is None or context.flight_duration_hours is None:
            return self._result(
                True, "Cabin class check skipped due to missing flight details"
            )

        cabin = context.cabin_class.lower()
        duration = context.flight_duration_hours
        if duration <= self.long_haul_hours and cabin not in self.allowed_classes:
            return self._result(
                False,
                (
                    f"Flights under {self.long_haul_hours} hours must use allowed cabins {sorted(self.allowed_classes)};"
                    f" requested '{context.cabin_class}'."
                ),
            )
        return self._result(
            True,
            f"Cabin '{context.cabin_class}' acceptable for {duration} hour flight.",
        )

    def message(self) -> str:  # pragma: no cover - static template
        return (
            f"Economy (or allowed cabins {sorted(self.allowed_classes)}) required unless flight exceeds"
            f" {self.long_haul_hours} hours."
        )


class FareEvidenceRule(PolicyRule):
    rule_id = "fare_evidence"

    def __init__(self, severity: str) -> None:
        super().__init__(severity)

    def evaluate(self, context: PolicyContext) -> PolicyResult:
        if context.fare_evidence_attached:
            return self._result(True, "Fare evidence attached")
        return self._result(
            False, "Screenshot or fare evidence must be attached to the request."
        )

    def message(self) -> str:  # pragma: no cover - static template
        return "Fare evidence (e.g., screenshot) is required."


class DrivingVsFlyingRule(PolicyRule):
    rule_id = "driving_vs_flying"

    def __init__(self, severity: str) -> None:
        super().__init__(severity)

    def evaluate(self, context: PolicyContext) -> PolicyResult:
        if context.driving_cost is None or context.flight_cost is None:
            return self._result(
                True, "Driving vs flying comparison skipped due to missing estimates"
            )

        if context.driving_cost > context.flight_cost:
            return self._result(
                False,
                (
                    f"Driving estimate {context.driving_cost} exceeds flight estimate {context.flight_cost};"
                    " reimbursement will be limited to the lesser cost."
                ),
            )
        return self._result(True, "Driving is lower or equal cost compared to flying.")

    def message(self) -> str:  # pragma: no cover - static template
        return "Reimbursement is limited to the lesser of driving vs flying costs."


class HotelComparisonRule(PolicyRule):
    rule_id = "hotel_comparison"

    def __init__(self, minimum_alternatives: int, severity: str) -> None:
        super().__init__(severity)
        self.minimum_alternatives = minimum_alternatives

    def evaluate(self, context: PolicyContext) -> PolicyResult:
        alternatives = context.comparable_hotels or []
        if len(alternatives) < self.minimum_alternatives:
            return self._result(
                False,
                f"Provide at least {self.minimum_alternatives} comparable hotel rates; {len(alternatives)} supplied.",
            )
        return self._result(
            True,
            f"{len(alternatives)} comparable hotels provided (minimum {self.minimum_alternatives}).",
        )

    def message(self) -> str:  # pragma: no cover - static template
        return f"At least {self.minimum_alternatives} comparable hotel options are required."


class LocalOvernightRule(PolicyRule):
    rule_id = "local_overnight"

    def __init__(self, min_distance_miles: float, severity: str) -> None:
        super().__init__(severity)
        self.min_distance_miles = float(min_distance_miles)

    def evaluate(self, context: PolicyContext) -> PolicyResult:
        if not context.overnight_stay:
            return self._result(True, "No overnight stay requested")
        if context.distance_from_office_miles is None:
            return self._result(
                True, "Local overnight check skipped due to missing distance data"
            )
        if context.distance_from_office_miles < self.min_distance_miles:
            return self._result(
                False,
                f"Overnight stays within {self.min_distance_miles} miles require waiver; distance is {context.distance_from_office_miles} miles.",
            )
        return self._result(
            True,
            f"Overnight stay is {context.distance_from_office_miles} miles from office (minimum {self.min_distance_miles}).",
        )

    def message(self) -> str:  # pragma: no cover - static template
        return (
            f"Overnight stays under {self.min_distance_miles} miles require a waiver."
        )


class MealPerDiemRule(PolicyRule):
    rule_id = "meal_per_diem"

    def __init__(self, severity: str) -> None:
        super().__init__(severity)

    def evaluate(self, context: PolicyContext) -> PolicyResult:
        if context.meals_provided and context.meal_per_diem_requested:
            return self._result(
                False,
                "Meal per diem should exclude conference-provided meals; adjust the request accordingly.",
            )
        return self._result(True, "Meal per diem request aligns with provided meals.")

    def message(self) -> str:  # pragma: no cover - static template
        return "Conference-provided meals must be excluded from per diem claims."


class NonReimbursableRule(PolicyRule):
    rule_id = "non_reimbursable"

    def __init__(self, blocked_keywords: Iterable[str], severity: str) -> None:
        super().__init__(severity)
        self.blocked_keywords = {kw.lower() for kw in blocked_keywords}

    def evaluate(self, context: PolicyContext) -> PolicyResult:
        expenses = context.expenses or []
        for expense in expenses:
            description = expense.description.lower()
            if any(keyword in description for keyword in self.blocked_keywords):
                return self._result(
                    False,
                    f"Expense '{expense.description}' includes non-reimbursable items ({', '.join(sorted(self.blocked_keywords))}).",
                )
        return self._result(True, "No non-reimbursable items detected.")

    def message(self) -> str:  # pragma: no cover - static template
        keywords = ", ".join(sorted(self.blocked_keywords))
        return f"Expenses cannot include non-reimbursable items such as {keywords}."


class ThirdPartyPaidRule(PolicyRule):
    rule_id = "third_party_paid"

    def __init__(self, severity: str) -> None:
        super().__init__(severity)

    def evaluate(self, context: PolicyContext) -> PolicyResult:
        payments = context.third_party_payments or []
        for payment in payments:
            itemized = bool(payment.get("itemized"))
            description = str(payment.get("description", "third-party payment"))
            if not itemized:
                return self._result(
                    False,
                    f"Third-party payment '{description}' must be itemized and excluded from reimbursement.",
                )
        return self._result(
            True, "Third-party payments are properly itemized or none provided."
        )

    def message(self) -> str:  # pragma: no cover - static template
        return "Third-party paid expenses must be itemized and excluded."


def _load_rule_config(
    config: dict[str, Any], key: str, default: dict[str, Any]
) -> dict[str, Any]:
    rules_cfg: dict[str, Any] = config.get("rules", {}) or {}
    rule_cfg: dict[str, Any] = rules_cfg.get(key, {}) or {}
    merged = default.copy()
    merged.update(rule_cfg)
    return merged


def _default_policy_path() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "config" / "policy.yaml"
        if candidate.exists():
            return candidate
    return None


class PolicyEngine:
    """Execute all policy-lite rules and aggregate their results."""

    def __init__(self, rules: Iterable[PolicyRule]):
        self.rules = list(rules)

    @classmethod
    def from_yaml(cls, content: str) -> PolicyEngine:
        config = yaml.safe_load(content) or {}

        advance_cfg = _load_rule_config(
            config,
            "advance_booking",
            {"days_required": 14, "severity": Severity.ADVISORY},
        )
        fare_comparison_cfg = _load_rule_config(
            config,
            "fare_comparison",
            {"max_over_lowest": Decimal("200"), "severity": Severity.BLOCKING},
        )
        cabin_class_cfg = _load_rule_config(
            config,
            "cabin_class",
            {
                "long_haul_hours": 5,
                "allowed_classes": ["economy"],
                "severity": Severity.BLOCKING,
            },
        )
        fare_evidence_cfg = _load_rule_config(
            config, "fare_evidence", {"severity": Severity.BLOCKING}
        )
        driving_vs_flying_cfg = _load_rule_config(
            config, "driving_vs_flying", {"severity": Severity.ADVISORY}
        )
        hotel_comparison_cfg = _load_rule_config(
            config,
            "hotel_comparison",
            {"minimum_alternatives": 2, "severity": Severity.ADVISORY},
        )
        local_overnight_cfg = _load_rule_config(
            config,
            "local_overnight",
            {"min_distance_miles": 50, "severity": Severity.ADVISORY},
        )
        meal_per_diem_cfg = _load_rule_config(
            config, "meal_per_diem", {"severity": Severity.ADVISORY}
        )
        non_reimbursable_cfg = _load_rule_config(
            config,
            "non_reimbursable",
            {
                "blocked_keywords": ["liquor", "alcohol", "personal"],
                "severity": Severity.BLOCKING,
            },
        )
        third_party_paid_cfg = _load_rule_config(
            config, "third_party_paid", {"severity": Severity.BLOCKING}
        )

        rules: list[PolicyRule] = [
            AdvanceBookingRule(
                days_required=int(advance_cfg["days_required"]),
                severity=str(advance_cfg["severity"]),
            ),
            FareComparisonRule(
                max_over_lowest=Decimal(fare_comparison_cfg["max_over_lowest"]),
                severity=str(fare_comparison_cfg["severity"]),
            ),
            CabinClassRule(
                long_haul_hours=float(cabin_class_cfg["long_haul_hours"]),
                allowed_classes=cabin_class_cfg["allowed_classes"],
                severity=str(cabin_class_cfg["severity"]),
            ),
            FareEvidenceRule(severity=str(fare_evidence_cfg["severity"])),
            DrivingVsFlyingRule(severity=str(driving_vs_flying_cfg["severity"])),
            HotelComparisonRule(
                minimum_alternatives=int(hotel_comparison_cfg["minimum_alternatives"]),
                severity=str(hotel_comparison_cfg["severity"]),
            ),
            LocalOvernightRule(
                min_distance_miles=float(local_overnight_cfg["min_distance_miles"]),
                severity=str(local_overnight_cfg["severity"]),
            ),
            MealPerDiemRule(severity=str(meal_per_diem_cfg["severity"])),
            NonReimbursableRule(
                blocked_keywords=non_reimbursable_cfg["blocked_keywords"],
                severity=str(non_reimbursable_cfg["severity"]),
            ),
            ThirdPartyPaidRule(severity=str(third_party_paid_cfg["severity"])),
        ]

        return cls(rules)

    @classmethod
    def from_file(cls, path: str | Path | None = None) -> PolicyEngine:
        target_path = Path(path) if path is not None else _default_policy_path()
        if target_path is None:
            raise FileNotFoundError("No policy.yaml configuration file found")
        content = target_path.read_text(encoding="utf-8")
        return cls.from_yaml(content)

    def validate(self, context: PolicyContext) -> list[PolicyResult]:
        return [rule.evaluate(context) for rule in self.rules]

    def blocking_results(self, context: PolicyContext) -> list[PolicyResult]:
        return [
            result
            for result in self.validate(context)
            if result.severity == Severity.BLOCKING and not result.passed
        ]
