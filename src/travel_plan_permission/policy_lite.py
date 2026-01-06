"""Diagnostics helpers for policy-lite rule evaluation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .policy import PolicyContext, PolicyEngine


@dataclass(frozen=True)
class RuleDiagnostic:
    """Structured diagnostics for a single policy rule."""

    rule_id: str
    missing_fields: list[str]
    message: str


_RULE_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "advance_booking": ("booking_date", "departure_date"),
    "fare_comparison": ("selected_fare", "lowest_fare"),
    "cabin_class": ("cabin_class", "flight_duration_hours"),
    "fare_evidence": ("fare_evidence_attached",),
    "driving_vs_flying": ("driving_cost", "flight_cost"),
    "hotel_comparison": ("comparable_hotels",),
    "local_overnight": ("overnight_stay", "distance_from_office_miles"),
    "meal_per_diem": ("meals_provided", "meal_per_diem_requested"),
    "non_reimbursable": ("expenses",),
    "third_party_paid": ("third_party_payments",),
}


def _missing_fields(context: PolicyContext, fields: Iterable[str]) -> list[str]:
    missing: list[str] = []
    for field in fields:
        if getattr(context, field, None) is None:
            missing.append(field)
    return missing


def _missing_inputs_for_rule(rule_id: str, context: PolicyContext) -> list[str]:
    missing: list[str] = []
    if rule_id == "local_overnight":
        if context.overnight_stay is None:
            missing.append("overnight_stay")
            return missing
        if context.overnight_stay and context.distance_from_office_miles is None:
            missing.append("distance_from_office_miles")
        return missing
    if rule_id == "meal_per_diem":
        if context.meals_provided is None:
            missing.append("meals_provided")
        if context.meal_per_diem_requested is None:
            missing.append("meal_per_diem_requested")
        return missing
    fields = _RULE_REQUIRED_FIELDS.get(rule_id, ())
    return _missing_fields(context, fields)


def diagnose_missing_inputs(
    context: PolicyContext, engine: PolicyEngine | None = None
) -> list[RuleDiagnostic]:
    """Return diagnostics for rules that cannot evaluate due to missing inputs."""

    policy_engine = engine or PolicyEngine.from_file()
    diagnostics: list[RuleDiagnostic] = []
    for rule in policy_engine.rules:
        missing = _missing_inputs_for_rule(rule.rule_id, context)
        if not missing:
            continue
        missing_list = ", ".join(missing)
        diagnostics.append(
            RuleDiagnostic(
                rule_id=rule.rule_id,
                missing_fields=missing,
                message=f"Missing required inputs for '{rule.rule_id}': {missing_list}.",
            )
        )
    return diagnostics


__all__ = ["RuleDiagnostic", "diagnose_missing_inputs"]
