"""Helpers for converting intake payloads into canonical models."""

from __future__ import annotations

import warnings
from collections.abc import Mapping
from typing import Any, Literal

from .canonical import load_trip_plan_input
from .models import TripPlan, TripStatus


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
    transportation_mode: Literal["air", "train", "car", "mixed"] | None = None,
) -> TripPlan:
    """Convert a minimal intake payload into a canonical TripPlan."""

    warnings.warn(
        "trip_plan_from_minimal is deprecated; use load_trip_plan_input instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    payload_dict = dict(payload)
    payload_dict.setdefault("type", "trip")
    plan_input = load_trip_plan_input(payload_dict)
    overrides: dict[str, object] = {"trip_id": trip_id, "status": status}
    if traveler_role is not None:
        overrides["traveler_role"] = traveler_role
    if department is not None:
        overrides["department"] = department
    if origin_city is not None:
        overrides["origin_city"] = origin_city
    if destination_city is not None:
        overrides["destination_city"] = destination_city
    if funding_source is not None:
        overrides["funding_source"] = funding_source
    if transportation_mode is not None:
        overrides["transportation_mode"] = transportation_mode

    return plan_input.plan.model_copy(update=overrides)
