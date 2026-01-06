"""Canonical TripPlan schema helpers and conversion utilities."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from .models import ExpenseCategory, TripPlan

_ZIP_PATTERN = re.compile(r"^[0-9]{5}(-[0-9]{4})?$")


class CanonicalFlightOutbound(BaseModel):
    carrier_flight: str | None = None
    depart_time: str | None = None
    arrive_time: str | None = None
    roundtrip_cost: Decimal | None = Field(default=None, ge=0)

    model_config = {"extra": "forbid"}


class CanonicalFlightReturn(BaseModel):
    carrier_flight: str | None = None
    depart_time: str | None = None
    arrive_time: str | None = None

    model_config = {"extra": "forbid"}


class CanonicalHotel(BaseModel):
    name: str | None = None
    address: str | None = None
    city_state: str | None = None
    nightly_rate: Decimal | None = Field(default=None, ge=0)
    nights: int | None = Field(default=None, ge=0)
    conference_hotel: bool | None = None
    price_compare_notes: str | None = None

    model_config = {"extra": "forbid"}


class CanonicalComparableHotel(BaseModel):
    name: str | None = None
    nightly_rate: Decimal | None = Field(default=None, ge=0)

    model_config = {"extra": "forbid"}


class CanonicalAttachments(BaseModel):
    conference_agenda: str | None = None

    model_config = {"extra": "forbid"}


class CanonicalAttestations(BaseModel):
    budget_ok: bool | None = None

    model_config = {"extra": "forbid"}


class CanonicalTripPlan(BaseModel):
    """Canonical TripPlan contract aligned to schemas/trip_plan.min.schema.json."""

    type: Literal["trip"]
    traveler_name: str = Field(..., min_length=1)
    business_purpose: str = Field(..., min_length=1)
    cost_center: str | None = None
    destination_zip: str = Field(..., pattern=_ZIP_PATTERN.pattern)
    city_state: str | None = None
    depart_date: date
    return_date: date
    event_registration_cost: Decimal | None = Field(default=None, ge=0)
    flight_pref_outbound: CanonicalFlightOutbound | None = None
    flight_pref_return: CanonicalFlightReturn | None = None
    lowest_cost_roundtrip: Decimal | None = Field(default=None, ge=0)
    parking_estimate: Decimal | None = Field(default=None, ge=0)
    hotel: CanonicalHotel | None = None
    comparable_hotels: list[CanonicalComparableHotel] | None = None
    ground_transport_pref: str | None = None
    notes: str | None = None
    attachments: CanonicalAttachments | None = None
    attestations: CanonicalAttestations | None = None

    model_config = {"extra": "forbid"}


def _slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").upper()
    return cleaned or "TRAVELER"


def _default_trip_id(plan: CanonicalTripPlan) -> str:
    return f"TRIP-{plan.depart_date:%Y%m%d}-{_slugify(plan.traveler_name)}"


def _format_destination(plan: CanonicalTripPlan) -> str:
    if plan.city_state:
        return f"{plan.city_state} {plan.destination_zip}".strip()
    return plan.destination_zip


def _add_cost(
    breakdown: dict[ExpenseCategory, Decimal],
    category: ExpenseCategory,
    amount: Decimal | None,
) -> None:
    if amount is None:
        return
    breakdown[category] = amount


def canonical_trip_plan_to_model(plan: CanonicalTripPlan) -> TripPlan:
    """Convert canonical TripPlan schema data to the internal TripPlan model."""

    breakdown: dict[ExpenseCategory, Decimal] = {}
    _add_cost(breakdown, ExpenseCategory.CONFERENCE_FEES, plan.event_registration_cost)

    airfare = None
    if plan.flight_pref_outbound and plan.flight_pref_outbound.roundtrip_cost is not None:
        airfare = plan.flight_pref_outbound.roundtrip_cost
    elif plan.lowest_cost_roundtrip is not None:
        airfare = plan.lowest_cost_roundtrip
    _add_cost(breakdown, ExpenseCategory.AIRFARE, airfare)

    _add_cost(breakdown, ExpenseCategory.GROUND_TRANSPORT, plan.parking_estimate)

    if plan.hotel and plan.hotel.nightly_rate is not None and plan.hotel.nights is not None:
        lodging_total = plan.hotel.nightly_rate * Decimal(plan.hotel.nights)
        _add_cost(breakdown, ExpenseCategory.LODGING, lodging_total)

    estimated_cost = sum(breakdown.values(), Decimal("0"))
    expected_costs = {category.value: amount for category, amount in breakdown.items()}

    transportation_mode: Literal["air", "train", "car", "mixed"] | None = None
    if airfare is not None:
        transportation_mode = "air"

    return TripPlan(
        trip_id=_default_trip_id(plan),
        traveler_name=plan.traveler_name,
        department=plan.cost_center,
        destination=_format_destination(plan),
        departure_date=plan.depart_date,
        return_date=plan.return_date,
        purpose=plan.business_purpose,
        transportation_mode=transportation_mode,
        expected_costs=expected_costs,
        estimated_cost=estimated_cost,
        expense_breakdown=breakdown,
    )


def load_trip_plan_payload(payload: dict[str, object]) -> TripPlan:
    """Load either canonical schema payloads or internal TripPlan payloads."""

    if payload.get("type") == "trip":
        canonical = CanonicalTripPlan.model_validate(payload)
        return canonical_trip_plan_to_model(canonical)
    return TripPlan.model_validate(payload)
