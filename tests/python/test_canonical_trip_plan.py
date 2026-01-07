from __future__ import annotations

import json
import warnings
from decimal import Decimal
from pathlib import Path

import travel_plan_permission.canonical as canonical
from travel_plan_permission.canonical import (
    CanonicalTripPlan,
    canonical_trip_plan_to_model,
    load_trip_plan_input,
    load_trip_plan_payload,
)
from travel_plan_permission.models import ExpenseCategory, TripPlan


def _load_fixture() -> dict[str, object]:
    fixture_path = (
        Path(__file__).resolve().parents[1] / "fixtures" / "sample_trip_plan_minimal.json"
    )
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def test_canonical_plan_validates() -> None:
    payload = _load_fixture()

    plan = CanonicalTripPlan.model_validate(payload)

    assert plan.type == "trip"
    assert plan.traveler_name


def test_canonical_conversion_builds_trip_plan() -> None:
    payload = _load_fixture()

    canonical_plan = CanonicalTripPlan.model_validate(payload)
    trip_plan = canonical_trip_plan_to_model(canonical_plan)

    assert isinstance(trip_plan, TripPlan)
    assert trip_plan.traveler_name == canonical_plan.traveler_name
    assert trip_plan.purpose == canonical_plan.business_purpose
    assert trip_plan.departure_date == canonical_plan.depart_date
    assert trip_plan.return_date == canonical_plan.return_date
    assert ExpenseCategory.CONFERENCE_FEES in trip_plan.expense_breakdown
    assert trip_plan.expense_breakdown[ExpenseCategory.CONFERENCE_FEES] == Decimal("350")
    assert trip_plan.expense_breakdown[ExpenseCategory.AIRFARE] == Decimal("550")
    assert trip_plan.expense_breakdown[ExpenseCategory.GROUND_TRANSPORT] == Decimal("36")
    assert trip_plan.expense_breakdown[ExpenseCategory.LODGING] == Decimal("630")
    assert trip_plan.estimated_cost == Decimal("1566")


def test_load_trip_plan_payload_handles_canonical() -> None:
    payload = _load_fixture()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        trip_plan = load_trip_plan_payload(payload)

    assert isinstance(trip_plan, TripPlan)
    assert trip_plan.trip_id.startswith("TRIP-")
    assert trip_plan.traveler_name == payload["traveler_name"]
    assert trip_plan.destination.endswith(payload["destination_zip"])


def test_load_trip_plan_payload_matches_loader() -> None:
    payload = _load_fixture()

    plan_input = load_trip_plan_input(payload)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        trip_plan = load_trip_plan_payload(payload)

    assert trip_plan.model_dump() == plan_input.plan.model_dump()


def test_canonical_trip_plan_to_model_matches_loader() -> None:
    payload = _load_fixture()

    canonical_plan = CanonicalTripPlan.model_validate(payload)
    trip_plan = canonical_trip_plan_to_model(canonical_plan)
    plan_input = load_trip_plan_input(payload)

    assert trip_plan.model_dump() == plan_input.plan.model_dump()


def test_load_trip_plan_payload_delegates_to_loader(monkeypatch) -> None:
    payload = _load_fixture()
    called: dict[str, dict[str, object]] = {}
    original_loader = canonical.load_trip_plan_input

    def _wrapped_loader(payload_dict: dict[str, object]) -> object:
        called["payload"] = payload_dict
        return original_loader(payload_dict)

    monkeypatch.setattr(canonical, "load_trip_plan_input", _wrapped_loader)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        load_trip_plan_payload(payload)

    assert called["payload"]["type"] == "trip"
