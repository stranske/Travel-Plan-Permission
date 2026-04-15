"""Planner-facing HTTP service for local and preview integration testing."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import parse_qs
from uuid import uuid4

import uvicorn
from fastapi import (
    Body,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, ValidationError

from .models import ExceptionRequest, ExceptionType, TripPlan
from .planner_auth import PlannerAuthConfig, authenticate_request
from .policy_api import (
    PlannerPolicySnapshot,
    PlannerPolicySnapshotRequest,
    PlannerProposalEvaluationRequest,
    PlannerProposalEvaluationResult,
    PlannerProposalOperationResponse,
    PlannerProposalStatusRequest,
    PlannerProposalSubmissionRequest,
    check_trip_plan,
    get_evaluation_result,
    get_policy_snapshot,
    poll_execution_status,
    submit_proposal,
)
from .portal_review import (
    PortalArtifact,
    PortalReviewState,
    portal_review_state,
    portal_validation_state,
)
from .review_workflow import ReviewAction, ReviewRequest, ReviewWorkflowStore
from .security import (
    DEFAULT_ROLES,
    AuditEventType,
    AuditLogEvent,
    Permission,
    RoleName,
    SecurityModel,
)

__all__ = [
    "PlannerProposalStore",
    "PortalDraft",
    "TripPlan",
    "check_trip_plan",
    "create_app",
    "get_policy_snapshot",
    "main",
]

_OPTIONAL_SNAPSHOT_BODY = Body(default=None)
_TEMPLATES = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent / "templates")
)
_PORTAL_CANONICAL_FIELDS: tuple[str, ...] = (
    "traveler_name",
    "business_purpose",
    "cost_center",
    "destination_zip",
    "city_state",
    "depart_date",
    "return_date",
    "event_registration_cost",
    "flight_pref_outbound.carrier_flight",
    "flight_pref_outbound.depart_time",
    "flight_pref_outbound.arrive_time",
    "flight_pref_outbound.roundtrip_cost",
    "flight_pref_return.carrier_flight",
    "flight_pref_return.depart_time",
    "flight_pref_return.arrive_time",
    "lowest_cost_roundtrip",
    "parking_estimate",
    "hotel.name",
    "hotel.address",
    "hotel.city_state",
    "hotel.nightly_rate",
    "hotel.nights",
    "hotel.conference_hotel",
    "hotel.price_compare_notes",
    "comparable_hotels[0].name",
    "comparable_hotels[0].nightly_rate",
    "ground_transport_pref",
    "notes",
)
_PORTAL_POLICY_FIELDS: tuple[str, ...] = (
    "booking_date",
    "selected_fare",
    "lowest_fare",
    "cabin_class",
    "flight_duration_hours",
    "fare_evidence_attached",
    "driving_cost",
    "flight_cost",
    "distance_from_office_miles",
    "overnight_stay",
    "meals_provided",
    "meal_per_diem_requested",
)
_PORTAL_FIELDS: tuple[str, ...] = _PORTAL_CANONICAL_FIELDS + _PORTAL_POLICY_FIELDS
_PORTAL_OPTIONAL_FIELDS = {
    "cost_center",
    "event_registration_cost",
    "flight_pref_outbound.carrier_flight",
    "flight_pref_outbound.depart_time",
    "flight_pref_outbound.arrive_time",
    "flight_pref_outbound.roundtrip_cost",
    "flight_pref_return.carrier_flight",
    "flight_pref_return.depart_time",
    "flight_pref_return.arrive_time",
    "lowest_cost_roundtrip",
    "parking_estimate",
    "hotel.name",
    "hotel.address",
    "hotel.city_state",
    "hotel.nightly_rate",
    "hotel.nights",
    "hotel.conference_hotel",
    "hotel.price_compare_notes",
    "comparable_hotels[0].name",
    "comparable_hotels[0].nightly_rate",
    "ground_transport_pref",
    "notes",
    "booking_date",
    "selected_fare",
    "lowest_fare",
    "cabin_class",
    "flight_duration_hours",
    "fare_evidence_attached",
    "driving_cost",
    "flight_cost",
    "distance_from_office_miles",
    "overnight_stay",
    "meals_provided",
    "meal_per_diem_requested",
}
_PORTAL_REQUIRED_FIELDS: tuple[str, ...] = tuple(
    field_name
    for field_name in _PORTAL_CANONICAL_FIELDS
    if field_name not in _PORTAL_OPTIONAL_FIELDS
)
_PORTAL_BOOLEAN_FIELDS = {
    "hotel.conference_hotel",
    "fare_evidence_attached",
    "overnight_stay",
    "meals_provided",
    "meal_per_diem_requested",
}
_PORTAL_MAX_DRAFTS = 64


@dataclass(frozen=True)
class PortalDraft:
    """Stored portal draft answers for request review and submission."""

    draft_id: str
    answers: dict[str, object]
    updated_at: datetime
    cached_artifacts: dict[str, PortalArtifact] = field(default_factory=dict)


@dataclass(frozen=True)
class DraftExceptionEntry:
    """Exception request scoped to a saved draft and optional review."""

    draft_id: str
    exception_index: int
    review_id: str | None
    traveler_name: str | None
    destination: str | None
    request: ExceptionRequest


@dataclass(frozen=True)
class RoleView:
    """Resolved role metadata for the admin portal."""

    role: RoleName
    permissions: tuple[Permission, ...]


class PlannerRuntimeConfigError(RuntimeError):
    """Raised when the planner-facing HTTP runtime is misconfigured."""


class PlannerRuntimeConfig(BaseModel):
    """Minimal runtime configuration required for planner-facing live tests."""

    base_url: str | None = Field(default=None)
    oidc_provider: str | None = Field(default=None)
    auth_mode: str | None = Field(default=None)
    access_token_configured: bool = Field(default=False)
    bootstrap_secret_configured: bool = Field(default=False)
    bootstrap_ttl_seconds: int | None = Field(default=None)
    missing_config: list[str] = Field(default_factory=list)
    invalid_config: list[str] = Field(default_factory=list)

    @classmethod
    def from_env(cls) -> PlannerRuntimeConfig:
        config = PlannerAuthConfig.from_env()
        return cls(
            base_url=config.base_url,
            oidc_provider=config.oidc_provider,
            auth_mode=config.auth_mode.value if config.auth_mode else None,
            access_token_configured=config.access_token_configured,
            bootstrap_secret_configured=config.bootstrap_secret_configured,
            bootstrap_ttl_seconds=config.bootstrap_ttl_seconds,
            missing_config=list(config.missing_config),
            invalid_config=list(config.invalid_config),
        )

    @property
    def is_ready(self) -> bool:
        """Return whether the required planner-facing config is present."""

        return not self.missing_config and not self.invalid_config

    def ensure_valid(self) -> None:
        """Raise a runtime error when the planner-facing config is not usable."""

        if self.is_ready:
            return
        problems: list[str] = []
        if self.missing_config:
            problems.append("missing: " + ", ".join(sorted(self.missing_config)))
        if self.invalid_config:
            problems.append("invalid: " + ", ".join(sorted(self.invalid_config)))
        raise PlannerRuntimeConfigError(
            "Planner HTTP service runtime is misconfigured ("
            + "; ".join(problems)
            + "). Supported auth modes: static-token, bootstrap-token. "
            + "Supported TPP_OIDC_PROVIDER values: azure_ad, okta, google."
        )


def _authorize_request(
    authorization: str | None,
    *,
    required_permission: Permission,
) -> None:
    config = PlannerAuthConfig.from_env()
    if not config.is_ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Planner auth config is not ready.",
        )
    try:
        authenticate_request(
            authorization,
            config=config,
            required_permission=required_permission,
        )
    except PermissionError as exc:
        detail = str(exc)
        status_code = (
            status.HTTP_401_UNAUTHORIZED
            if detail == "Missing bearer token."
            else status.HTTP_403_FORBIDDEN
        )
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


def _copy_exception_request(request: ExceptionRequest) -> ExceptionRequest:
    """Return a deep copy of an exception request."""

    return ExceptionRequest.model_validate(request.model_dump(mode="python"))


def _resolve_role_view(role_name: str | None) -> RoleView:
    """Resolve a role name into a UI-ready role/permission view."""

    try:
        role = RoleName(role_name or RoleName.TRAVELER.value)
    except ValueError:
        role = RoleName.TRAVELER
    permissions = tuple(sorted(DEFAULT_ROLES[role].permissions, key=lambda item: item.value))
    return RoleView(role=role, permissions=permissions)


class PlannerReadinessResponse(BaseModel):
    """Health/readiness payload for the local service runtime."""

    service: str = "travel-plan-permission"
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: str
    config: PlannerRuntimeConfig


class PlannerPolicySnapshotHttpRequest(BaseModel):
    """HTTP wrapper for the snapshot seam when a plan is supplied directly."""

    trip_plan: TripPlan
    request: PlannerPolicySnapshotRequest | None = None


class PlannerProposalSubmissionHttpRequest(BaseModel):
    """HTTP wrapper for the proposal submission seam."""

    trip_plan: TripPlan
    request: PlannerProposalSubmissionRequest


@dataclass
class StoredProposal:
    """Persisted proposal context needed by the thin HTTP adapter layer."""

    trip_plan: TripPlan
    request: PlannerProposalSubmissionRequest
    response: PlannerProposalOperationResponse


@dataclass
class PlannerProposalStore:
    """In-memory proposal store for local and preview live testing."""

    plans_by_trip_id: dict[str, TripPlan] = field(default_factory=dict)
    proposals_by_execution_id: dict[str, StoredProposal] = field(default_factory=dict)
    portal_drafts_by_id: dict[str, PortalDraft] = field(default_factory=dict)
    manager_reviews: ReviewWorkflowStore = field(default_factory=ReviewWorkflowStore)
    exception_requests_by_draft_id: dict[str, list[ExceptionRequest]] = field(
        default_factory=dict
    )
    security: SecurityModel = field(default_factory=SecurityModel)

    def remember_plan(self, trip_plan: TripPlan) -> None:
        """Store the latest planner trip payload by trip identifier."""

        self.plans_by_trip_id[trip_plan.trip_id] = trip_plan.model_copy(deep=True)

    def lookup_trip_plan(self, trip_id: str) -> TripPlan | None:
        """Return a previously stored plan by trip identifier."""

        trip_plan = self.plans_by_trip_id.get(trip_id)
        if trip_plan is None:
            return None
        return trip_plan.model_copy(deep=True)

    def record_submission(
        self,
        trip_plan: TripPlan,
        request: PlannerProposalSubmissionRequest,
        response: PlannerProposalOperationResponse,
    ) -> None:
        """Store proposal context keyed by the stable execution identifier."""

        self.remember_plan(trip_plan)
        execution_id = response.result_payload.get("execution_id")
        if not isinstance(execution_id, str):
            raise ValueError(
                "Planner proposal response missing required string execution_id"
            )
        self.proposals_by_execution_id[execution_id] = StoredProposal(
            trip_plan=trip_plan.model_copy(deep=True),
            request=request.model_copy(deep=True),
            response=response.model_copy(deep=True),
        )

    def lookup_submission(self, execution_id: str) -> StoredProposal | None:
        """Return a previously stored proposal submission by execution identifier."""

        stored = self.proposals_by_execution_id.get(execution_id)
        if stored is None:
            return None
        return StoredProposal(
            trip_plan=stored.trip_plan.model_copy(deep=True),
            request=stored.request.model_copy(deep=True),
            response=stored.response.model_copy(deep=True),
        )

    def save_portal_draft(self, answers: dict[str, object]) -> PortalDraft:
        """Persist portal answers so a review route can be revisited."""

        if len(self.portal_drafts_by_id) >= _PORTAL_MAX_DRAFTS:
            oldest_draft_id = min(
                self.portal_drafts_by_id.items(),
                key=lambda item: item[1].updated_at,
            )[0]
            del self.portal_drafts_by_id[oldest_draft_id]
            self.exception_requests_by_draft_id.pop(oldest_draft_id, None)
        draft = PortalDraft(
            draft_id=uuid4().hex[:12],
            answers=dict(answers),
            updated_at=datetime.now(UTC),
        )
        self.portal_drafts_by_id[draft.draft_id] = draft
        self.security.audit_log.record(
            event_type=AuditEventType.REQUEST,
            actor=str(answers.get("traveler_name") or "portal-traveler"),
            subject=draft.draft_id,
            outcome="draft_saved",
            metadata={"surface": "workflow-portal"},
        )
        return draft

    def cache_portal_artifacts(
        self,
        draft_id: str,
        artifacts: dict[str, PortalArtifact],
    ) -> PortalDraft | None:
        """Persist generated portal artifacts for repeated downloads."""

        draft = self.portal_drafts_by_id.get(draft_id)
        if draft is None:
            return None
        updated = replace(
            draft,
            updated_at=datetime.now(UTC),
            cached_artifacts=dict(artifacts),
        )
        self.portal_drafts_by_id[draft_id] = updated
        return updated

    def lookup_portal_draft(self, draft_id: str) -> PortalDraft | None:
        """Return a previously stored portal draft by identifier."""

        draft = self.portal_drafts_by_id.get(draft_id)
        if draft is None:
            return None
        return PortalDraft(
            draft_id=draft.draft_id,
            answers=dict(draft.answers),
            updated_at=draft.updated_at,
            cached_artifacts=dict(draft.cached_artifacts),
        )

    def create_manager_review(self, review: PortalReviewState) -> ReviewRequest:
        """Persist a manager review request for a submitted portal draft."""

        if (
            review.trip_plan is None
            or review.policy_snapshot is None
            or review.policy_result is None
        ):
            raise ValueError("Manager review requires a completed portal review state.")
        trip_plan = review.trip_plan.model_copy(deep=True)
        trip_plan.exception_requests = self.list_exception_requests(review.draft_id)
        manager_review = self.manager_reviews.create_or_get(
            draft_id=review.draft_id,
            trip_plan=trip_plan,
            policy_snapshot=review.policy_snapshot,
            policy_result=review.policy_result,
        )
        self.security.audit_log.record(
            event_type=AuditEventType.REVIEW,
            actor="workflow-portal",
            subject=manager_review.review_id,
            outcome="submitted_for_manager_review",
            metadata={"draft_id": review.draft_id, "trip_id": trip_plan.trip_id},
        )
        return manager_review

    def lookup_manager_review(self, review_id: str) -> ReviewRequest | None:
        """Return a persisted manager review by identifier."""

        return self.manager_reviews.lookup(review_id)

    def lookup_manager_review_for_draft(self, draft_id: str) -> ReviewRequest | None:
        """Return the persisted manager review for a portal draft, if any."""

        return self.manager_reviews.lookup_by_draft(draft_id)

    def list_manager_reviews(self) -> list[ReviewRequest]:
        """Return the manager review queue ordered by most recent activity."""

        return self.manager_reviews.list_reviews()

    def apply_manager_review_action(
        self,
        review_id: str,
        *,
        action: ReviewAction,
        actor_id: str,
        rationale: str,
    ) -> ReviewRequest:
        """Persist a manager decision against an existing review request."""

        updated = self.manager_reviews.apply_action(
            review_id,
            action=action,
            actor_id=actor_id,
            rationale=rationale,
        )
        self.security.audit_log.record(
            event_type=AuditEventType.REVIEW,
            actor=actor_id,
            subject=review_id,
            outcome=action.value,
            metadata={"draft_id": updated.draft_id, "status": updated.status.value},
        )
        return updated

    def list_exception_requests(self, draft_id: str) -> list[ExceptionRequest]:
        """Return exception requests attached to a draft."""

        return [
            _copy_exception_request(item)
            for item in self.exception_requests_by_draft_id.get(draft_id, [])
        ]

    def create_exception_request(
        self,
        draft_id: str,
        exception_request: ExceptionRequest,
    ) -> list[ExceptionRequest]:
        """Attach a new exception request to a draft."""

        stored = self.exception_requests_by_draft_id.setdefault(draft_id, [])
        stored.append(_copy_exception_request(exception_request))
        self.security.audit_log.record(
            event_type=AuditEventType.EXCEPTION,
            actor=exception_request.requestor,
            subject=draft_id,
            outcome="requested",
            metadata={
                "exception_type": exception_request.type.value,
                "approval_level": (
                    exception_request.approval_level.value
                    if exception_request.approval_level is not None
                    else None
                ),
            },
        )
        return self.list_exception_requests(draft_id)

    def decide_exception_request(
        self,
        draft_id: str,
        *,
        exception_index: int,
        actor_id: str,
        approved: bool,
        notes: str | None = None,
    ) -> ExceptionRequest:
        """Approve or reject an exception request tied to a draft."""

        requests = self.exception_requests_by_draft_id.get(draft_id)
        if requests is None or exception_index < 0 or exception_index >= len(requests):
            raise KeyError(
                f"No exception request {exception_index} found for draft '{draft_id}'."
            )
        target = requests[exception_index]
        if approved:
            target.approve(approver_id=actor_id, notes=notes)
            outcome = "approved"
        else:
            target.reject()
            outcome = "rejected"
        metadata: dict[str, object] = {
            "exception_type": target.type.value,
            "exception_index": exception_index,
            "status": target.status.value,
        }
        if notes is not None:
            metadata["notes"] = notes
        self.security.audit_log.record(
            event_type=AuditEventType.EXCEPTION,
            actor=actor_id,
            subject=draft_id,
            outcome=outcome,
            metadata=metadata,
        )
        return _copy_exception_request(target)

    def list_exception_entries(self) -> list[DraftExceptionEntry]:
        """Return flattened exception entries ordered by newest draft activity."""

        entries: list[DraftExceptionEntry] = []
        for draft_id, requests in self.exception_requests_by_draft_id.items():
            draft = self.portal_drafts_by_id.get(draft_id)
            review = self.lookup_manager_review_for_draft(draft_id)
            traveler_name = None
            destination = None
            if review is not None:
                traveler_name = review.trip_plan.traveler_name
                destination = review.trip_plan.destination
            elif draft is not None:
                traveler_name = str(draft.answers.get("traveler_name") or "") or None
                destination = str(draft.answers.get("city_state") or "") or None
            for index, request in enumerate(requests):
                entries.append(
                    DraftExceptionEntry(
                        draft_id=draft_id,
                        exception_index=index,
                        review_id=review.review_id if review is not None else None,
                        traveler_name=traveler_name,
                        destination=destination,
                        request=_copy_exception_request(request),
                    )
                )
        entries.sort(
            key=lambda item: (
                item.request.requested_at,
                item.request.requestor,
                item.request.type.value,
            ),
            reverse=True,
        )
        return entries

    def list_audit_events(self) -> list[AuditLogEvent]:
        """Return the current audit log ordered by most recent first."""

        return sorted(
            self.security.audit_log.events,
            key=lambda event: event.timestamp,
            reverse=True,
        )


def _readiness_response() -> PlannerReadinessResponse:
    config = PlannerRuntimeConfig.from_env()
    return PlannerReadinessResponse(
        status="ready" if config.is_ready else "misconfigured",
        config=config,
    )


def _submission_status_request(
    stored: StoredProposal,
    *,
    proposal_id: str,
    execution_id: str,
) -> PlannerProposalStatusRequest:
    request = stored.request
    return PlannerProposalStatusRequest(
        trip_id=request.trip_id,
        proposal_id=proposal_id,
        proposal_version=request.proposal_version,
        execution_id=execution_id,
        transport_pattern=request.transport_pattern,
        correlation_id=request.correlation_id,
    )


def _evaluation_request(
    stored: StoredProposal,
    *,
    execution_id: str,
) -> PlannerProposalEvaluationRequest:
    request = stored.request
    return PlannerProposalEvaluationRequest(
        trip_id=request.trip_id,
        proposal_id=request.proposal_id,
        proposal_version=request.proposal_version,
        execution_id=execution_id,
        correlation_id=request.correlation_id,
    )


def _normalize_portal_value(field_name: str, raw_value: str) -> object | None:
    value = raw_value.strip()
    if not value:
        return None
    if field_name in _PORTAL_BOOLEAN_FIELDS:
        normalized = value.casefold()
        if normalized in {"true", "yes", "on", "1"}:
            return True
        if normalized in {"false", "no", "off", "0"}:
            return False
    return value


def _portal_answers_from_encoded_body(body: bytes) -> dict[str, object]:
    answers: dict[str, object] = {}
    parsed = parse_qs(body.decode("utf-8"), keep_blank_values=False)
    for field_name in _PORTAL_FIELDS:
        values = parsed.get(field_name)
        if not values:
            continue
        normalized = _normalize_portal_value(field_name, values[-1])
        if normalized is None:
            continue
        answers[field_name] = normalized
    return answers


def _canonical_payload_from_answers(answers: dict[str, object]) -> dict[str, object]:
    payload: dict[str, object] = {"type": "trip"}
    for field_name in _PORTAL_CANONICAL_FIELDS:
        value = answers.get(field_name)
        if value is None:
            continue
        segments = field_name.split(".")
        current: dict[str, object] = payload
        for index, segment in enumerate(segments):
            is_last = index == len(segments) - 1
            if "[" in segment and segment.endswith("]"):
                container_name, item_index_text = segment[:-1].split("[", 1)
                item_index = int(item_index_text)
                existing = current.get(container_name)
                if not isinstance(existing, list):
                    existing = []
                    current[container_name] = existing
                while len(existing) <= item_index:
                    existing.append({})
                if is_last:
                    existing[item_index] = value
                    continue
                next_value = existing[item_index]
                if not isinstance(next_value, dict):
                    next_value = {}
                    existing[item_index] = next_value
                current = next_value
                continue
            if is_last:
                current[segment] = value
            else:
                next_value = current.get(segment)
                if not isinstance(next_value, dict):
                    next_value = {}
                    current[segment] = next_value
                current = next_value
    return payload


def _portal_template_context(
    request: Request,
    review: PortalReviewState | None = None,
    *,
    exceptions: list[ExceptionRequest] | None = None,
    error_message: str | None = None,
) -> dict[str, object]:
    answers = review.answers if review is not None else {}
    return {
        "request": request,
        "answers": answers,
        "review": review,
        "exceptions": exceptions or [],
        "exception_types": tuple(ExceptionType),
        "ground_transport_options": (
            "rideshare/taxi",
            "rental car",
            "public transit",
            "personal vehicle",
        ),
        "optional_fields": _PORTAL_OPTIONAL_FIELDS,
        "error_message": error_message,
    }


def _manager_review_queue_context(
    request: Request,
    reviews: list[ReviewRequest],
    *,
    role_view: RoleView,
) -> dict[str, object]:
    return {
        "request": request,
        "reviews": reviews,
        "role_view": role_view,
        "role_can_approve": Permission.APPROVE in role_view.permissions,
    }


def _manager_review_detail_context(
    request: Request,
    review: ReviewRequest,
    *,
    role_view: RoleView,
    exceptions: list[ExceptionRequest] | None = None,
    audit_events: list[AuditLogEvent] | None = None,
    error_message: str | None = None,
) -> dict[str, object]:
    return {
        "request": request,
        "review": review,
        "role_view": role_view,
        "role_can_approve": Permission.APPROVE in role_view.permissions,
        "exceptions": exceptions or [],
        "audit_events": audit_events or [],
        "error_message": error_message,
        "review_actions": tuple(ReviewAction),
    }


def _admin_dashboard_context(
    request: Request,
    *,
    role_view: RoleView,
    reviews: list[ReviewRequest],
    exception_entries: list[DraftExceptionEntry],
    audit_events: list[AuditLogEvent],
    runtime_config: PlannerRuntimeConfig,
) -> dict[str, object]:
    return {
        "request": request,
        "role_view": role_view,
        "role_can_approve": Permission.APPROVE in role_view.permissions,
        "role_can_configure": Permission.CONFIGURE in role_view.permissions,
        "available_roles": tuple(RoleName),
        "reviews": reviews,
        "exception_entries": exception_entries,
        "audit_events": audit_events,
        "runtime_config": runtime_config,
    }


def create_app(store: PlannerProposalStore | None = None) -> FastAPI:
    """Create the planner-facing ASGI application."""

    proposal_store = store or PlannerProposalStore()
    app = FastAPI(
        title="Travel Plan Permission Planner Service",
        version="0.1.0",
        summary="Thin HTTP adapter over the planner-facing policy API builders.",
    )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/portal", response_class=HTMLResponse)
    def portal_home(request: Request) -> HTMLResponse:
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="portal_home.html",
            context={
                "service_ready": _readiness_response().status == "ready",
                "runtime_config": PlannerRuntimeConfig.from_env(),
            },
        )

    @app.get("/portal/draft/new", response_class=HTMLResponse)
    def portal_draft_form(request: Request) -> HTMLResponse:
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="draft_entry.html",
            context=_portal_template_context(request, None),
        )

    @app.post("/portal/draft")
    async def portal_draft_review(request: Request) -> Response:
        answers = _portal_answers_from_encoded_body(await request.body())
        review = portal_validation_state(
            answers,
            required_fields=_PORTAL_REQUIRED_FIELDS,
            canonical_payload_builder=_canonical_payload_from_answers,
        )
        if review.missing_fields or review.validation_errors:
            return _TEMPLATES.TemplateResponse(
                request=request,
                name="validation_feedback.html",
                context=_portal_template_context(request, review, exceptions=[]),
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        draft = proposal_store.save_portal_draft(answers)
        if review.artifacts:
            proposal_store.cache_portal_artifacts(draft.draft_id, review.artifacts)
        return RedirectResponse(
            url=request.url_for("portal_review_detail", draft_id=draft.draft_id),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    @app.get(
        "/portal/review/{draft_id}",
        response_class=HTMLResponse,
        name="portal_review_detail",
    )
    def portal_review_detail(request: Request, draft_id: str) -> HTMLResponse:
        draft = proposal_store.lookup_portal_draft(draft_id)
        if draft is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No portal draft found for '{draft_id}'.",
            )
        review = portal_review_state(
            draft.draft_id,
            draft.answers,
            required_fields=_PORTAL_REQUIRED_FIELDS,
            canonical_payload_builder=_canonical_payload_from_answers,
            manager_review=proposal_store.lookup_manager_review_for_draft(
                draft.draft_id
            ),
        )
        if review.artifacts and not draft.cached_artifacts:
            proposal_store.cache_portal_artifacts(draft.draft_id, review.artifacts)
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="review_summary.html",
            context=_portal_template_context(
                request,
                review,
                exceptions=proposal_store.list_exception_requests(draft_id),
            ),
        )

    @app.post("/portal/review/{draft_id}/exceptions")
    async def portal_submit_exception_request(
        request: Request,
        draft_id: str,
    ) -> RedirectResponse:
        draft = proposal_store.lookup_portal_draft(draft_id)
        if draft is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No portal draft found for '{draft_id}'.",
            )
        parsed = parse_qs(
            (await request.body()).decode("utf-8"),
            keep_blank_values=True,
        )
        try:
            exception_type = ExceptionType(
                parsed.get("exception_type", [""])[-1].strip()
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Select a valid exception type.",
            ) from exc

        supporting_doc = parsed.get("supporting_doc", [""])[-1].strip()
        amount_text = parsed.get("amount", [""])[-1].strip()
        review = portal_review_state(
            draft.draft_id,
            draft.answers,
            required_fields=_PORTAL_REQUIRED_FIELDS,
            canonical_payload_builder=_canonical_payload_from_answers,
            manager_review=proposal_store.lookup_manager_review_for_draft(draft.draft_id),
        )
        if review.artifacts and not draft.cached_artifacts:
            proposal_store.cache_portal_artifacts(draft.draft_id, review.artifacts)
        try:
            parsed_amount = Decimal(amount_text) if amount_text else None
        except InvalidOperation as exc:
            return _TEMPLATES.TemplateResponse(
                request=request,
                name="review_summary.html",
                context=_portal_template_context(
                    request,
                    review,
                    exceptions=proposal_store.list_exception_requests(draft_id),
                    error_message="Amount must be a valid non-negative decimal value.",
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        try:
            exception_request = ExceptionRequest(
                type=exception_type,
                justification=parsed.get("justification", [""])[-1].strip(),
                requestor=str(draft.answers.get("traveler_name") or "portal-traveler"),
                amount=parsed_amount,
                supporting_docs=[supporting_doc] if supporting_doc else [],
            )
        except ValidationError as exc:
            messages = "; ".join(
                error["msg"] for error in exc.errors() if error.get("msg")
            )
            return _TEMPLATES.TemplateResponse(
                request=request,
                name="review_summary.html",
                context=_portal_template_context(
                    request,
                    review,
                    exceptions=proposal_store.list_exception_requests(draft_id),
                    error_message=messages or "Provide a valid exception request.",
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        proposal_store.create_exception_request(draft_id, exception_request)
        return RedirectResponse(
            url=request.url_for("portal_review_detail", draft_id=draft_id),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    @app.post("/portal/review/{draft_id}/submit", response_class=HTMLResponse)
    def portal_submit_request(
        request: Request,
        draft_id: str,
        authorization: str | None = Header(default=None),
    ) -> HTMLResponse:
        _authorize_request(
            authorization,
            required_permission=Permission.CREATE,
        )
        draft = proposal_store.lookup_portal_draft(draft_id)
        if draft is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No portal draft found for '{draft_id}'.",
            )
        review = portal_review_state(
            draft.draft_id,
            draft.answers,
            required_fields=_PORTAL_REQUIRED_FIELDS,
            canonical_payload_builder=_canonical_payload_from_answers,
        )
        if (
            review.trip_plan is None
            or review.missing_fields
            or review.validation_errors
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Complete the request review before submitting the portal draft.",
            )
        submission_request = PlannerProposalSubmissionRequest(
            trip_id=review.trip_plan.trip_id,
            proposal_id=f"{review.trip_plan.trip_id.lower()}-portal-request",
            proposal_version="portal-v1",
            payload={
                "channel": "workflow-portal",
                "draft_id": draft_id,
                "review_surface": "browser",
            },
        )
        submission_response = submit_proposal(review.trip_plan, submission_request)
        proposal_store.record_submission(
            review.trip_plan,
            submission_request,
            submission_response,
        )
        manager_review = proposal_store.create_manager_review(review)
        review = portal_review_state(
            draft.draft_id,
            draft.answers,
            required_fields=_PORTAL_REQUIRED_FIELDS,
            canonical_payload_builder=_canonical_payload_from_answers,
            submission_response=submission_response,
            manager_review=manager_review,
        )
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="review_summary.html",
            context=_portal_template_context(
                request,
                review,
                exceptions=proposal_store.list_exception_requests(draft_id),
            ),
        )

    @app.get("/portal/manager/reviews", response_class=HTMLResponse)
    def portal_manager_review_queue(
        request: Request,
        authorization: str | None = Header(default=None),
        actor_role: str | None = Query(default=RoleName.TRAVELER.value),
    ) -> HTMLResponse:
        _authorize_request(
            authorization,
            required_permission=Permission.VIEW,
        )
        role_view = _resolve_role_view(actor_role)
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="manager_review_queue.html",
            context=_manager_review_queue_context(
                request,
                proposal_store.list_manager_reviews(),
                role_view=role_view,
            ),
        )

    @app.get(
        "/portal/manager/reviews/{review_id}",
        response_class=HTMLResponse,
        name="portal_manager_review_detail",
    )
    def portal_manager_review_detail(
        request: Request,
        review_id: str,
        authorization: str | None = Header(default=None),
        actor_role: str | None = Query(default=RoleName.TRAVELER.value),
    ) -> HTMLResponse:
        _authorize_request(
            authorization,
            required_permission=Permission.VIEW,
        )
        role_view = _resolve_role_view(actor_role)
        review = proposal_store.lookup_manager_review(review_id)
        if review is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No manager review found for '{review_id}'.",
            )
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="manager_review_detail.html",
            context=_manager_review_detail_context(
                request,
                review,
                role_view=role_view,
                exceptions=proposal_store.list_exception_requests(review.draft_id),
                audit_events=[
                    event
                    for event in proposal_store.list_audit_events()
                    if event.subject in {review.review_id, review.draft_id}
                ],
            ),
        )

    @app.post("/portal/manager/reviews/{review_id}/decision")
    async def portal_manager_review_decision(
        request: Request,
        review_id: str,
        authorization: str | None = Header(default=None),
        actor_role: str | None = Query(default=RoleName.TRAVELER.value),
    ) -> Response:
        _authorize_request(
            authorization,
            required_permission=Permission.APPROVE,
        )
        role_view = _resolve_role_view(actor_role)
        parsed = parse_qs(
            (await request.body()).decode("utf-8"), keep_blank_values=True
        )
        action_name = parsed.get("action", [""])[-1].strip()
        actor_id = parsed.get("actor_id", [""])[-1].strip()
        rationale = parsed.get("rationale", [""])[-1].strip()

        review = proposal_store.lookup_manager_review(review_id)
        if review is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No manager review found for '{review_id}'.",
            )
        if not actor_id:
            return _TEMPLATES.TemplateResponse(
                request=request,
                name="manager_review_detail.html",
                context=_manager_review_detail_context(
                    request,
                    review,
                    role_view=role_view,
                    exceptions=proposal_store.list_exception_requests(review.draft_id),
                    audit_events=[
                        event
                        for event in proposal_store.list_audit_events()
                        if event.subject in {review.review_id, review.draft_id}
                    ],
                    error_message="Manager actor ID is required.",
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        try:
            action = ReviewAction(action_name)
            proposal_store.apply_manager_review_action(
                review_id,
                action=action,
                actor_id=actor_id,
                rationale=rationale,
            )
        except ValueError as exc:
            refreshed = proposal_store.lookup_manager_review(review_id) or review
            return _TEMPLATES.TemplateResponse(
                request=request,
                name="manager_review_detail.html",
                context=_manager_review_detail_context(
                    request,
                    refreshed,
                    role_view=role_view,
                    exceptions=proposal_store.list_exception_requests(refreshed.draft_id),
                    audit_events=[
                        event
                        for event in proposal_store.list_audit_events()
                        if event.subject in {refreshed.review_id, refreshed.draft_id}
                    ],
                    error_message=str(exc),
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        return RedirectResponse(
            url=request.url_for("portal_manager_review_detail", review_id=review_id),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    @app.post("/portal/admin/exceptions/{draft_id}/{exception_index}/decision")
    async def portal_exception_decision(
        request: Request,
        draft_id: str,
        exception_index: int,
        authorization: str | None = Header(default=None),
        actor_role: str | None = Query(default=RoleName.TRAVELER.value),
    ) -> RedirectResponse:
        _authorize_request(
            authorization,
            required_permission=Permission.APPROVE,
        )
        parsed = parse_qs(
            (await request.body()).decode("utf-8"),
            keep_blank_values=True,
        )
        actor_id = parsed.get("actor_id", [""])[-1].strip()
        if not actor_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Actor ID is required for exception decisions.",
            )
        try:
            proposal_store.decide_exception_request(
                draft_id,
                exception_index=exception_index,
                actor_id=actor_id,
                approved=parsed.get("decision", ["reject"])[-1].strip() == "approve",
                notes=parsed.get("notes", [""])[-1].strip() or None,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Exception request not found.",
            ) from exc
        review = proposal_store.lookup_manager_review_for_draft(draft_id)
        resolved_role = _resolve_role_view(actor_role).role.value
        if review is not None:
            return RedirectResponse(
                url=str(
                    request.url_for(
                        "portal_manager_review_detail", review_id=review.review_id
                    )
                )
                + f"?actor_role={resolved_role}",
                status_code=status.HTTP_303_SEE_OTHER,
            )
        return RedirectResponse(
            url=str(request.url_for("portal_admin_dashboard"))
            + f"?actor_role={resolved_role}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    @app.get(
        "/portal/admin",
        response_class=HTMLResponse,
        name="portal_admin_dashboard",
    )
    def portal_admin_dashboard(
        request: Request,
        authorization: str | None = Header(default=None),
        actor_role: str | None = Query(default=RoleName.TRAVELER.value),
    ) -> HTMLResponse:
        _authorize_request(
            authorization,
            required_permission=Permission.VIEW,
        )
        role_view = _resolve_role_view(actor_role)
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="portal_admin.html",
            context=_admin_dashboard_context(
                request,
                role_view=role_view,
                reviews=proposal_store.list_manager_reviews(),
                exception_entries=proposal_store.list_exception_entries(),
                audit_events=proposal_store.list_audit_events(),
                runtime_config=PlannerRuntimeConfig.from_env(),
            ),
        )

    @app.get("/portal/review/{draft_id}/artifacts/{artifact_name}")
    def portal_artifact(
        draft_id: str,
        artifact_name: str,
    ) -> Response:
        draft = proposal_store.lookup_portal_draft(draft_id)
        if draft is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No portal draft found for '{draft_id}'.",
            )
        artifacts = draft.cached_artifacts
        if not artifacts:
            review = portal_review_state(
                draft.draft_id,
                draft.answers,
                required_fields=_PORTAL_REQUIRED_FIELDS,
                canonical_payload_builder=_canonical_payload_from_answers,
            )
            artifacts = review.artifacts
            if artifacts:
                proposal_store.cache_portal_artifacts(draft.draft_id, artifacts)
        artifact = artifacts.get(artifact_name)
        if artifact is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No artifact named '{artifact_name}' for draft '{draft_id}'.",
            )
        proposal_store.security.audit_log.record(
            event_type=AuditEventType.EXPORT,
            actor="workflow-portal",
            subject=draft_id,
            outcome="artifact_downloaded",
            metadata={"artifact": artifact_name},
        )
        return Response(
            content=artifact.content,
            media_type=artifact.media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{artifact.filename}"'
            },
        )

    @app.get(
        "/readyz",
        response_model=PlannerReadinessResponse,
        responses={503: {"model": PlannerReadinessResponse}},
    )
    def readyz(response: Response) -> PlannerReadinessResponse:
        readiness = _readiness_response()
        if readiness.status != "ready":
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return readiness

    @app.get("/api/planner/policy-snapshot", response_model=PlannerPolicySnapshot)
    def policy_snapshot(
        trip_id: str | None = Query(default=None),
        request_body: PlannerPolicySnapshotHttpRequest | None = _OPTIONAL_SNAPSHOT_BODY,
        authorization: str | None = Header(default=None),
    ) -> PlannerPolicySnapshot:
        _authorize_request(
            authorization,
            required_permission=Permission.VIEW,
        )
        trip_plan: TripPlan | None = None
        snapshot_request: PlannerPolicySnapshotRequest | None = None

        if request_body is not None:
            trip_plan = request_body.trip_plan
            snapshot_request = request_body.request
            proposal_store.remember_plan(trip_plan)
        elif trip_id is not None:
            trip_plan = proposal_store.lookup_trip_plan(trip_id)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Provide either a snapshot request body or a stored trip_id.",
            )

        if trip_plan is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No stored trip plan found for trip_id '{trip_id}'.",
            )

        snapshot_request = snapshot_request or PlannerPolicySnapshotRequest(
            trip_id=trip_plan.trip_id
        )
        try:
            return get_policy_snapshot(trip_plan, snapshot_request)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    @app.post(
        "/api/planner/proposals",
        response_model=PlannerProposalOperationResponse,
    )
    def proposal_submission(
        payload: PlannerProposalSubmissionHttpRequest,
        authorization: str | None = Header(default=None),
    ) -> PlannerProposalOperationResponse:
        _authorize_request(
            authorization,
            required_permission=Permission.CREATE,
        )
        try:
            planner_response = submit_proposal(payload.trip_plan, payload.request)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        proposal_store.record_submission(
            payload.trip_plan,
            payload.request,
            planner_response,
        )
        return planner_response

    @app.get(
        "/api/planner/proposals/{proposal_id}/executions/{execution_id}",
        response_model=PlannerProposalOperationResponse,
    )
    def proposal_status(
        proposal_id: str,
        execution_id: str,
        authorization: str | None = Header(default=None),
    ) -> PlannerProposalOperationResponse:
        _authorize_request(
            authorization,
            required_permission=Permission.VIEW,
        )
        stored = proposal_store.lookup_submission(execution_id)
        if stored is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No stored proposal found for execution_id '{execution_id}'.",
            )
        if stored.request.proposal_id != proposal_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"Execution '{execution_id}' does not belong to proposal '{proposal_id}'."
                ),
            )
        status_request = _submission_status_request(
            stored,
            proposal_id=proposal_id,
            execution_id=execution_id,
        )
        try:
            return poll_execution_status(stored.trip_plan, status_request)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    @app.get(
        "/api/planner/executions/{execution_id}/evaluation-result",
        response_model=PlannerProposalEvaluationResult,
    )
    def evaluation_result(
        execution_id: str,
        authorization: str | None = Header(default=None),
    ) -> PlannerProposalEvaluationResult:
        _authorize_request(
            authorization,
            required_permission=Permission.VIEW,
        )
        stored = proposal_store.lookup_submission(execution_id)
        if stored is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No stored proposal found for execution_id '{execution_id}'.",
            )
        evaluation_request = _evaluation_request(stored, execution_id=execution_id)
        try:
            return get_evaluation_result(stored.trip_plan, evaluation_request)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    return app


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tpp-planner-service",
        description="Run the planner-facing Travel Plan Permission HTTP service.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind.")
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="TCP port for the local planner-facing service.",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable uvicorn auto-reload for local development.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the planner-facing HTTP service."""

    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        PlannerRuntimeConfig.from_env().ensure_valid()
    except PlannerRuntimeConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    uvicorn.run(
        "travel_plan_permission.http_service:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
