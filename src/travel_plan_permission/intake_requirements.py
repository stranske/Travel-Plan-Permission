"""Organization-owned evidence and cost-coverage requirements for trip planners."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CollectionMode = Literal["automatic", "researchable", "traveler"]
EvidenceKind = Literal[
    "calculation",
    "fare_quote",
    "provider_rate",
    "policy_rate",
    "traveler_confirmation",
]


class PlannerIntakeRequirement(BaseModel):
    """One cost or evidence component the planner must resolve explicitly."""

    code: str
    category: str
    title: str
    summary: str
    collection_mode: CollectionMode
    evidence_kind: EvidenceKind
    required_inputs: list[str] = Field(default_factory=list)
    output_fields: list[str] = Field(default_factory=list)
    research_prompt: str | None = None
    policy_reference: str | None = None


class PlannerIntakeRequirementCatalog(BaseModel):
    """Versioned requirements published to trip-planner before proposal handoff."""

    contract_version: str = "tpp-intake-requirements/v1"
    organization_id: str = "tpp"
    requirements: list[PlannerIntakeRequirement]


def get_intake_requirement_catalog() -> PlannerIntakeRequirementCatalog:
    """Return the organization-owned checklist with collection and research guidance."""

    requirements = [
        PlannerIntakeRequirement(
            code="airport_access",
            category="ground_transport",
            title="Travel to and from the departure airport",
            summary=(
                "Compare personal-vehicle mileage, tolls, rideshare, or another airport-access "
                "plan for both legs and apply the commuting and temporary-work-location rules."
            ),
            collection_mode="researchable",
            evidence_kind="calculation",
            required_inputs=[
                "traveler_residence_address",
                "official_domicile_address",
                "departure_airport",
            ],
            output_fields=[
                "ground_transport.mileage_planned",
                "ground_transport.mileage_miles",
                "ground_transport.mileage_cost",
                "ground_transport.rideshare_cost",
                "airport_access_evidence",
            ],
            research_prompt=(
                "Compare practical personal-vehicle and rideshare options between the traveler "
                "residence, official domicile, and departure airport. Calculate direct route "
                "distances and a roundtrip reimbursable-mile estimate under Missouri's rules: "
                "home-to-official-domicile travel is commuting and not reimbursable; use the "
                "most direct route; and when a return from a temporary location ends at home, "
                "do not claim more than the shorter distance to home or official domicile. Use "
                "the organization workbook's current mileage rate and return the route arithmetic "
                "in structured details. Do not assume that driving is preferred."
            ),
            policy_reference="mileage_and_commuting",
        ),
        PlannerIntakeRequirement(
            code="airport_parking",
            category="ground_transport",
            title="Airport parking",
            summary=(
                "Identify a parking facility, daily rate, chargeable duration, total estimate, "
                "and provider evidence when the traveler plans to drive."
            ),
            collection_mode="researchable",
            evidence_kind="provider_rate",
            required_inputs=["departure_airport", "parking_days"],
            output_fields=["parking_estimate", "parking_evidence"],
            research_prompt=(
                "Compare current airport-operated lots and reputable off-airport shuttle parking "
                "operators. Calculate totals for the trip duration including known taxes, fees, "
                "and reservation charges; identify covered or uncovered parking, shuttle and "
                "terminal access, cancellation terms, and whether a reservation is required. "
                "Include multiple categories when available and do not default to a previously "
                "used operator or to the official airport lot."
            ),
            policy_reference="driving_vs_flying",
        ),
        PlannerIntakeRequirement(
            code="intercity_transport",
            category="airfare",
            title="Intercity transportation",
            summary=(
                "Capture the selected flight, train, or driving option, the lowest reasonable "
                "comparison, and time-stamped fare evidence."
            ),
            collection_mode="researchable",
            evidence_kind="fare_quote",
            required_inputs=["departure_airport", "destination_airport", "travel_dates"],
            output_fields=["selected_fare", "lowest_fare", "fare_evidence_attached"],
            research_prompt=(
                "Research practical roundtrip transportation options for the trip dates and "
                "return a selected candidate plus lower-cost comparables with source URLs."
            ),
            policy_reference="fare_evidence",
        ),
        PlannerIntakeRequirement(
            code="destination_transfers",
            category="ground_transport",
            title="Airport or station transfers",
            summary=(
                "Estimate arrival and departure transfers between the destination airport or "
                "station and the hotel or principal meeting location."
            ),
            collection_mode="researchable",
            evidence_kind="provider_rate",
            required_inputs=["destination_airport", "hotel_or_meeting_address"],
            output_fields=["destination_transfer_estimate", "destination_transfer_evidence"],
            research_prompt=(
                "Compare public transit, shuttle, and reasonable taxi or rideshare transfer "
                "options for both arrival and departure."
            ),
        ),
        PlannerIntakeRequirement(
            code="local_mobility",
            category="ground_transport",
            title="Local transportation during the trip",
            summary=(
                "Account for meeting commutes and incidental business travel rather than "
                "treating an unknown amount as zero."
            ),
            collection_mode="researchable",
            evidence_kind="provider_rate",
            required_inputs=["hotel_or_meeting_address", "local_trip_pattern"],
            output_fields=["ground_transport_pref", "ground_transport_estimate"],
            research_prompt=(
                "Estimate a prudent local transit plan using public transportation where "
                "practical and a bounded taxi or rideshare allowance when useful."
            ),
        ),
        PlannerIntakeRequirement(
            code="lodging",
            category="lodging",
            title="Lodging and comparison evidence",
            summary=(
                "Collect the selected rate and at least two prudent nearby comparisons, with "
                "dates, fees, source URLs, and required business amenities."
            ),
            collection_mode="researchable",
            evidence_kind="provider_rate",
            required_inputs=["meeting_address", "travel_dates", "room_requirements"],
            output_fields=["hotel", "comparable_hotels"],
            research_prompt=(
                "Research a prudent business-hotel set near the main event, including rate, "
                "distance, relevant amenities, and official or booking evidence."
            ),
            policy_reference="hotel_comparison",
        ),
        PlannerIntakeRequirement(
            code="meals_incidentals",
            category="meals",
            title="Meals and incidental allowance",
            summary=(
                "Derive eligible meals by date from travel timing and provided meals, then apply "
                "the organization destination per-diem table and incidental allowance."
            ),
            collection_mode="automatic",
            evidence_kind="policy_rate",
            required_inputs=["travel_times", "event_meal_schedule", "destination_zip"],
            output_fields=["meal_counts", "meal_per_diem_requested", "meals_provided"],
            research_prompt=(
                "Resolve the destination per-diem rate from the organization rate table and "
                "explain which meals remain eligible after supplied meals are excluded."
            ),
            policy_reference="meal_per_diem",
        ),
        PlannerIntakeRequirement(
            code="registration_other",
            category="other",
            title="Registration and other anticipated expenses",
            summary=(
                "Confirm registration, baggage, required connectivity, meeting parking, and any "
                "other expected business expense or explicitly mark each not applicable."
            ),
            collection_mode="traveler",
            evidence_kind="traveler_confirmation",
            output_fields=["event_registration_cost", "other_estimates"],
        ),
        PlannerIntakeRequirement(
            code="organization_attestations",
            category="administrative",
            title="Organization and approval details",
            summary=(
                "Collect the cost center, section-budget attestation, and approval fields that "
                "only the traveler or organization can supply."
            ),
            collection_mode="traveler",
            evidence_kind="traveler_confirmation",
            output_fields=["cost_center", "attestations.budget_ok"],
        ),
    ]
    return PlannerIntakeRequirementCatalog(requirements=requirements)
