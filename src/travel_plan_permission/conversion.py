"""Helpers for converting intake payloads into canonical models."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from .models import ExpenseCategory, TripPlan, TripStatus


def _coerce_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _get_nested(payload: Mapping[str, Any], *path: str) -> object | None:
    current: object = payload
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _build_destination(payload: Mapping[str, Any]) -> str:
    city_state = _get_nested(payload, "city_state")
    destination_zip = _get_nested(payload, "destination_zip")
    if city_state and destination_zip:
        return f"{city_state} {destination_zip}"
    if city_state:
        return str(city_state)
    if destination_zip:
        return str(destination_zip)
    raise ValueError("Minimal payload must include city_state or destination_zip")


def trip_plan_from_minimal(
    payload: Mapping[str, Any],
    *,
    trip_id: str,
    status: TripStatus = TripStatus.DRAFT,
    traveler_role: str | None = None,
    department: str | None = None,
    origin_city: str | None = None,
    destination_city: str | None = None,
    funding_source: str | None = None,
    transportation_mode: str | None = None,
) -> TripPlan:
    """Convert a minimal intake payload into a canonical TripPlan."""

    expected_costs: dict[str, Decimal] = {}
    expense_breakdown: dict[ExpenseCategory, Decimal] = {}

    def add_cost(category: ExpenseCategory, amount: Decimal | None) -> None:
        if amount is None:
            return
        expected_costs[category.value] = amount
        expense_breakdown[category] = amount

    airfare_cost = _coerce_decimal(_get_nested(payload, "flight_pref_outbound", "roundtrip_cost"))
    if airfare_cost is None:
        airfare_cost = _coerce_decimal(_get_nested(payload, "lowest_cost_roundtrip"))
    add_cost(ExpenseCategory.AIRFARE, airfare_cost)

    nightly_rate = _coerce_decimal(_get_nested(payload, "hotel", "nightly_rate"))
    nights = _get_nested(payload, "hotel", "nights")
    lodging_cost: Decimal | None = None
    if nightly_rate is not None and nights is not None:
        lodging_cost = nightly_rate * Decimal(str(nights))
    add_cost(ExpenseCategory.LODGING, lodging_cost)

    registration_cost = _coerce_decimal(_get_nested(payload, "event_registration_cost"))
    add_cost(ExpenseCategory.CONFERENCE_FEES, registration_cost)

    parking_cost = _coerce_decimal(_get_nested(payload, "parking_estimate"))
    add_cost(ExpenseCategory.GROUND_TRANSPORT, parking_cost)

    estimated_cost = sum(expense_breakdown.values(), Decimal("0"))

    traveler_name = payload.get("traveler_name")
    if not traveler_name:
        raise ValueError("Minimal payload must include traveler_name")
    business_purpose = payload.get("business_purpose")
    if not business_purpose:
        raise ValueError("Minimal payload must include business_purpose")
    depart_date = payload.get("depart_date")
    return_date = payload.get("return_date")
    if not depart_date or not return_date:
        raise ValueError("Minimal payload must include depart_date and return_date")

    return TripPlan(
        trip_id=trip_id,
        traveler_name=str(traveler_name),
        traveler_role=traveler_role,
        department=department,
        destination=_build_destination(payload),
        origin_city=origin_city,
        destination_city=destination_city,
        departure_date=depart_date,
        return_date=return_date,
        purpose=str(business_purpose),
        transportation_mode=transportation_mode,
        expected_costs=expected_costs,
        funding_source=funding_source,
        estimated_cost=estimated_cost,
        status=status,
        expense_breakdown=expense_breakdown,
        selected_providers={},
    )
