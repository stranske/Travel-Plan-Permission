from __future__ import annotations

import json
import warnings
from decimal import Decimal
from pathlib import Path

import pytest

import travel_plan_permission.canonical as canonical
from travel_plan_permission.canonical import (
    CanonicalTripPlan,
    TripPlanInput,
    canonical_trip_plan_to_model,
    load_trip_plan_input,
    load_trip_plan_payload,
)
from travel_plan_permission.models import ExpenseCategory, GroundTransport, TripPlan
from travel_plan_permission.policy_api import check_trip_plan


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
    assert trip_plan.comparable_hotels == [Decimal("185"), Decimal("199")]


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


def test_load_trip_plan_payload_returns_loader_plan(monkeypatch) -> None:
    payload = _load_fixture()
    base_plan = load_trip_plan_input(payload).plan
    delegated_plan = base_plan.model_copy(update={"traveler_name": "Delegated Traveler"})

    def _wrapped_loader(_payload_dict: dict[str, object]) -> TripPlanInput:
        return TripPlanInput(plan=delegated_plan)

    monkeypatch.setattr(canonical, "load_trip_plan_input", _wrapped_loader)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        trip_plan = load_trip_plan_payload(payload)

    assert trip_plan.traveler_name == "Delegated Traveler"


@pytest.mark.parametrize(
    ("selected", "lowest", "fare_issue"),
    [("550", "480", False), ("900", "480", True), ("0", "0", False)],
)
def test_canonical_fares_reach_policy_evaluation(
    selected: str, lowest: str, fare_issue: bool
) -> None:
    payload = _load_fixture()
    payload["flight_pref_outbound"] = {"roundtrip_cost": selected}
    payload["lowest_cost_roundtrip"] = lowest

    plan = load_trip_plan_input(payload).plan

    assert plan.selected_fare == Decimal(selected)
    assert plan.lowest_fare == Decimal(lowest)
    assert plan.expense_breakdown[ExpenseCategory.AIRFARE] == Decimal(selected)
    issues = [issue for issue in check_trip_plan(plan).issues if issue.code == "fare_comparison"]
    assert bool(issues) is fare_issue
    assert all("requires selected and lowest" not in issue.message for issue in issues)


@pytest.mark.parametrize(
    ("selected", "lowest"), [(None, "480"), ("550", None), (None, None)]
)
def test_canonical_conversion_preserves_missing_fare_fields(
    selected: str | None, lowest: str | None
) -> None:
    payload = _load_fixture()
    payload["flight_pref_outbound"] = {"roundtrip_cost": selected}
    payload["lowest_cost_roundtrip"] = lowest

    plan = load_trip_plan_input(payload).plan

    assert plan.selected_fare == (Decimal(selected) if selected is not None else None)
    assert plan.lowest_fare == (Decimal(lowest) if lowest is not None else None)


def test_canonical_structured_ground_transport_survives_model_roundtrip() -> None:
    payload = _load_fixture()
    payload["ground_transport_estimate"] = "999"
    payload["ground_transport"] = {
        "mileage_planned": True,
        "mileage_miles": "40",
        "mileage_cost": "29",
        "rideshare_planned": True,
        "rideshare_cost": "25",
        "shuttle_planned": True,
        "shuttle_cost": "10",
        "rental_planned": True,
        "rental_cost": "100",
        "rental_company": "Rental Co",
        "rental_daily_rate": "50",
        "rental_reason": "Site visits",
    }

    converted = load_trip_plan_input(payload)
    plan = TripPlan.model_validate_json(converted.plan.model_dump_json())

    assert isinstance(plan.ground_transport, GroundTransport)
    assert plan.ground_transport.model_dump() == converted.canonical.ground_transport.model_dump()
    # 164 itemized transport plus 36 parking; aggregate estimate is not added again.
    assert plan.expense_breakdown[ExpenseCategory.GROUND_TRANSPORT] == Decimal("200")
    assert plan.expected_costs["ground_transport"] == Decimal("200")
    assert plan.estimated_cost == Decimal("1730")


@pytest.mark.parametrize("ground", [None, {}, {"rideshare_planned": True}])
def test_canonical_ground_transport_keeps_aggregate_without_itemized_costs(ground) -> None:
    payload = _load_fixture()
    payload["ground_transport"] = ground
    payload["ground_transport_estimate"] = "80"

    plan = load_trip_plan_input(payload).plan

    assert plan.expense_breakdown[ExpenseCategory.GROUND_TRANSPORT] == Decimal("116")
    assert plan.estimated_cost == Decimal("1646")


def test_canonical_zero_transport_cost_does_not_restore_aggregate_estimate() -> None:
    payload = _load_fixture()
    payload["ground_transport"] = {"rideshare_cost": "0"}
    payload["ground_transport_estimate"] = "80"

    plan = load_trip_plan_input(payload).plan

    assert plan.ground_transport.rideshare_cost == Decimal("0")
    assert plan.expense_breakdown[ExpenseCategory.GROUND_TRANSPORT] == Decimal("36")
    assert plan.estimated_cost == Decimal("1566")


@pytest.mark.parametrize(
    "costs",
    [
        {"ground_transport": {"rideshare_cost": "0"}, "ground_transport_estimate": "80"},
        {"ground_transport_estimate": "0"},
        {"parking_estimate": "0"},
    ],
)
def test_canonical_explicit_zero_ground_cost_remains_in_breakdowns(costs) -> None:
    payload = _load_fixture()
    payload.update(ground_transport=None, ground_transport_estimate=None, parking_estimate=None)
    payload.update(costs)

    plan = load_trip_plan_input(payload).plan

    assert plan.expense_breakdown[ExpenseCategory.GROUND_TRANSPORT] == Decimal("0")
    assert plan.expected_costs["ground_transport"] == Decimal("0")
    assert plan.estimated_cost == Decimal("1530")


def test_canonical_absent_ground_cost_remains_absent() -> None:
    payload = _load_fixture()
    payload.update(ground_transport=None, ground_transport_estimate=None, parking_estimate=None)

    plan = load_trip_plan_input(payload).plan

    assert ExpenseCategory.GROUND_TRANSPORT not in plan.expense_breakdown
    assert "ground_transport" not in plan.expected_costs
