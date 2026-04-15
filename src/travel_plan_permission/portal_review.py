"""Shared portal validation and review-state builders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from pydantic import ValidationError

from .canonical import CanonicalTripPlan, canonical_trip_plan_to_model
from .models import TripPlan
from .policy_api import (
    PlannerPolicySnapshot,
    PlannerPolicySnapshotRequest,
    PlannerProposalOperationResponse,
    check_trip_plan,
    get_policy_snapshot,
    render_travel_spreadsheet_bytes,
)
from .prompt_flow import build_output_bundle, generate_questions, required_field_gaps

if TYPE_CHECKING:
    from .review_workflow import ReviewRequest


@dataclass(frozen=True)
class PortalArtifact:
    """Generated portal artifact metadata and payload."""

    filename: str
    content: bytes
    media_type: str


@dataclass(frozen=True)
class PortalReviewState:
    """Computed portal review context derived from a draft."""

    draft_id: str
    answers: dict[str, object]
    missing_fields: list[str]
    next_questions: list[dict[str, object]]
    validation_errors: list[str]
    canonical_payload: dict[str, object] | None
    trip_plan: TripPlan | None
    policy_snapshot: PlannerPolicySnapshot | None
    policy_result: Any | None
    artifacts: dict[str, PortalArtifact]
    submission_response: PlannerProposalOperationResponse | None = None
    manager_review: ReviewRequest | None = None


def _review_validation_errors(exc: ValidationError) -> list[str]:
    errors: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        errors.append(f"{location}: {error['msg']}")
    return errors


def _portal_artifacts(
    *,
    canonical: CanonicalTripPlan,
    plan: TripPlan,
    answers: dict[str, object],
) -> dict[str, PortalArtifact]:
    itinerary_excel = render_travel_spreadsheet_bytes(plan, canonical_plan=canonical)
    bundle = build_output_bundle(itinerary_excel=itinerary_excel, answers=answers)
    itinerary_payload = bundle["itinerary_excel"]
    summary_payload = bundle["summary_pdf"]
    if not isinstance(itinerary_payload, dict):
        raise RuntimeError("itinerary_excel bundle payload must be a mapping")
    if not isinstance(summary_payload, dict):
        raise RuntimeError("summary_pdf bundle payload must be a mapping")
    return {
        "itinerary": PortalArtifact(
            filename=str(itinerary_payload["filename"]),
            content=itinerary_excel,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        "summary": PortalArtifact(
            filename=str(summary_payload["filename"]),
            content=bytes(summary_payload["content"]),
            media_type=str(summary_payload["mime_type"]),
        ),
    }


def portal_validation_state(
    answers: dict[str, object],
    *,
    required_fields: tuple[str, ...],
    canonical_payload_builder: Callable[[dict[str, object]], dict[str, object]],
) -> PortalReviewState:
    missing_fields = required_field_gaps(answers, required_fields=required_fields)
    next_questions: list[dict[str, object]] = [
        {
            "prompt": question.prompt,
            "fields": ", ".join(question.fields),
            "kind": question.kind,
        }
        for question in generate_questions(answers, max_questions=4)
    ]
    validation_errors: list[str] = []
    canonical_payload: dict[str, object] | None = None

    if not missing_fields:
        canonical_payload = canonical_payload_builder(answers)
        try:
            CanonicalTripPlan.model_validate(canonical_payload)
        except ValidationError as exc:
            validation_errors = _review_validation_errors(exc)

    return PortalReviewState(
        draft_id="",
        answers=answers,
        missing_fields=missing_fields,
        next_questions=next_questions,
        validation_errors=validation_errors,
        canonical_payload=canonical_payload,
        trip_plan=None,
        policy_snapshot=None,
        policy_result=None,
        artifacts={},
    )


def portal_review_state(
    draft_id: str,
    answers: dict[str, object],
    *,
    required_fields: tuple[str, ...],
    canonical_payload_builder: Callable[[dict[str, object]], dict[str, object]],
    submission_response: PlannerProposalOperationResponse | None = None,
    manager_review: ReviewRequest | None = None,
) -> PortalReviewState:
    validation_state = portal_validation_state(
        answers,
        required_fields=required_fields,
        canonical_payload_builder=canonical_payload_builder,
    )
    missing_fields = validation_state.missing_fields
    next_questions = validation_state.next_questions
    validation_errors = validation_state.validation_errors
    canonical_payload = validation_state.canonical_payload
    trip_plan: TripPlan | None = None
    policy_snapshot: PlannerPolicySnapshot | None = None
    policy_result: Any | None = None
    artifacts: dict[str, PortalArtifact] = {}

    if not missing_fields and canonical_payload is not None and not validation_errors:
        canonical = CanonicalTripPlan.model_validate(canonical_payload)
        trip_plan = canonical_trip_plan_to_model(canonical)
        policy_snapshot = get_policy_snapshot(
            trip_plan,
            PlannerPolicySnapshotRequest(trip_id=trip_plan.trip_id),
        )
        policy_result = check_trip_plan(trip_plan)
        artifacts = _portal_artifacts(
            canonical=canonical,
            plan=trip_plan,
            answers=answers,
        )

    return PortalReviewState(
        draft_id=draft_id,
        answers=answers,
        missing_fields=missing_fields,
        next_questions=next_questions,
        validation_errors=validation_errors,
        canonical_payload=canonical_payload,
        trip_plan=trip_plan,
        policy_snapshot=policy_snapshot,
        policy_result=policy_result,
        artifacts=artifacts,
        submission_response=submission_response,
        manager_review=manager_review,
    )
