"""Owner-scoped, immutable handoff receipts over the real portal review workflow."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Any, Literal
from urllib.parse import parse_qs, urlencode

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .http_contract_models import PortalDraft, PortalReceiptBinding
from .planner_auth import (
    PlannerAuthConfig,
    PlannerAuthContext,
    PlannerAuthMode,
    _oidc_provider_settings,
)
from .policy_api import PlannerProposalSubmissionRequest
from .portal_handoff import issue_handoff_token, verify_handoff_token
from .portal_review import (
    portal_validation_state,
)
from .review_workflow import ReviewRequest, ReviewStatus
from .security import Permission

if TYPE_CHECKING:
    from .http_service import PlannerProposalStore

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]{1,80}$")]
_SNAPSHOT_VERSION_QUERY = Query()


class PortalHandoffRequest(BaseModel):
    """A caller's retry key and complete immutable portal-form snapshot."""

    model_config = ConfigDict(extra="forbid")
    handoff_id: Identifier
    snapshot_version: Identifier
    answers: dict[str, str]

    @field_validator("answers")
    @classmethod
    def bound_answers(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 80 or any(
            len(k) > 100 or len(v) > 4096 for k, v in value.items()
        ):
            raise ValueError("Portal answers exceed the bounded handoff contract.")
        if len(json.dumps(value).encode()) > 65536:
            raise ValueError("Portal answers exceed the bounded handoff contract.")
        return value


class PortalReceipt(BaseModel):
    """Truthful persisted submission and manager-review evidence, without form data."""

    contract_version: Literal["portal-receipt/v1"] = "portal-receipt/v1"
    handoff_id: str
    snapshot_version: str
    snapshot_sha256: str
    draft_id: str
    state: Literal["prepared", "submitted", "pending_review", "decision_recorded"]
    prepared_at: datetime
    observed_at: datetime
    request_id: str | None = None
    execution_id: str | None = None
    review_id: str | None = None
    submitted_at: datetime | None = None
    decision: str | None = None
    decision_at: datetime | None = None


def identity_namespace(context: PlannerAuthContext) -> str:
    """Bind OIDC subjects to their verified issuer and configured audience."""

    if context.auth_mode == PlannerAuthMode.OIDC:
        config = PlannerAuthConfig.from_env()
        return json.dumps(
            [_oidc_provider_settings(config)["issuer"], config.oidc_audience]
        )
    return context.provider


def owner_matches(binding: PortalReceiptBinding, context: PlannerAuthContext) -> bool:
    """Never derive request ownership from a display name or a correlation ID."""

    return (
        binding.owner_mode,
        binding.owner_provider,
        binding.owner_subject,
        binding.owner_namespace,
    ) == (
        context.auth_mode.value,
        context.provider,
        context.subject,
        identity_namespace(context),
    )


def authorize_draft_owner(draft: PortalDraft, context: PlannerAuthContext) -> None:
    """Preserve legacy portal behavior while protecting newly bound drafts."""

    if draft.receipt_binding is not None and not owner_matches(
        draft.receipt_binding, context
    ):
        raise HTTPException(status_code=404, detail="Portal receipt not found.")


def review_visible(
    store: Any, review: ReviewRequest, context: PlannerAuthContext
) -> bool:
    """Bound review pages must not become an alternate cross-owner read path."""

    draft = store.lookup_portal_draft(review.draft_id)
    if draft is None or draft.receipt_binding is None:
        return True  # Legacy, unbound review behavior is unchanged.
    binding = draft.receipt_binding
    same_namespace = (
        binding.owner_mode,
        binding.owner_provider,
        binding.owner_namespace,
    ) == (context.auth_mode.value, context.provider, identity_namespace(context))
    return owner_matches(binding, context) or (
        same_namespace and context.can(Permission.APPROVE)
    )


def receipt_for(draft: PortalDraft, review: ReviewRequest | None) -> PortalReceipt:
    """Read only actual persisted submission/review state; preparation is not sent."""

    binding = draft.receipt_binding
    if binding is None:
        raise HTTPException(status_code=404, detail="Portal receipt not found.")
    submission = draft.submission_response
    state: Literal["prepared", "submitted", "pending_review", "decision_recorded"] = (
        "prepared"
    )
    decision = None
    decision_at = None
    if submission is not None:
        state = "submitted"
    if review is not None:
        state = "pending_review"
        if review.status != ReviewStatus.PENDING_MANAGER_REVIEW:
            state = "decision_recorded"
            decision = review.status.value
            decision_at = review.updated_at
    return PortalReceipt(
        handoff_id=binding.handoff_id,
        snapshot_version=binding.snapshot_version,
        snapshot_sha256=binding.snapshot_sha256,
        draft_id=draft.draft_id,
        state=state,
        prepared_at=binding.prepared_at,
        observed_at=datetime.now(UTC),
        request_id=submission.request_id if submission else None,
        execution_id=(
            str(submission.result_payload["execution_id"]) if submission else None
        ),
        review_id=review.review_id if review else None,
        submitted_at=review.submitted_at if review else None,
        decision=decision,
        decision_at=decision_at,
    )


def register_portal_receipt_routes(app: FastAPI, store: PlannerProposalStore) -> None:
    """Register bounded identity-authenticated handoff creation and status lookup."""

    from . import http_service as service

    def context_for(
        request: Request, authorization: str | None, permission: Permission
    ) -> PlannerAuthContext:
        context = service._authorize_request(
            authorization,
            required_permission=permission,
            route=service._route_identifier(request),
        )
        if context.auth_mode == PlannerAuthMode.STATIC_TOKEN:
            raise HTTPException(
                status_code=403, detail="An individual traveler identity is required."
            )
        return context

    def binding_for(
        context: PlannerAuthContext,
        handoff_id: str,
        version: str = "",
        digest: str = "",
    ) -> PortalReceiptBinding:
        return PortalReceiptBinding(
            owner_mode=context.auth_mode.value,
            owner_provider=context.provider,
            owner_subject=context.subject,
            owner_namespace=identity_namespace(context),
            handoff_id=handoff_id,
            snapshot_version=version,
            snapshot_sha256=digest,
            prepared_at=datetime.now(UTC),
        )

    @app.post("/api/planner/portal-handoffs", response_model=PortalReceipt)
    def prepare_handoff(
        request: Request,
        response: Response,
        payload: PortalHandoffRequest,
        authorization: str | None = Header(default=None),
    ) -> PortalReceipt:
        context = context_for(request, authorization, Permission.CREATE)
        if set(payload.answers) - set(service._PORTAL_FIELDS):
            raise HTTPException(status_code=422, detail="Unknown portal answer field.")
        answers = service._portal_answers_from_encoded_body(
            urlencode(payload.answers).encode()
        )
        review = portal_validation_state(
            answers,
            required_fields=service._PORTAL_REQUIRED_FIELDS,
            canonical_payload_builder=service._canonical_payload_from_answers,
        )
        if review.missing_fields or review.validation_errors:
            raise HTTPException(
                status_code=422, detail="Complete valid portal answers are required."
            )
        digest = hashlib.sha256(
            json.dumps(answers, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        draft = store.prepare_portal_receipt(
            answers,
            binding_for(context, payload.handoff_id, payload.snapshot_version, digest),
        )
        response.headers["Cache-Control"] = "no-store"
        return receipt_for(draft, store.lookup_manager_review_for_draft(draft.draft_id))

    @app.get("/api/planner/portal-handoffs/{handoff_id}", response_model=PortalReceipt)
    def get_receipt(
        request: Request,
        response: Response,
        handoff_id: Identifier,
        snapshot_version: Identifier = _SNAPSHOT_VERSION_QUERY,
        authorization: str | None = Header(default=None),
    ) -> PortalReceipt:
        context = context_for(request, authorization, Permission.VIEW)
        response.headers["Cache-Control"] = "no-store"
        return store.read_portal_receipt(
            binding_for(context, handoff_id), snapshot_version
        )

    @app.post("/api/planner/portal-handoffs/{handoff_id}/browser-session")
    def browser_session(
        request: Request,
        response: Response,
        handoff_id: Identifier,
        snapshot_version: Identifier = _SNAPSHOT_VERSION_QUERY,
        authorization: str | None = Header(default=None),
    ) -> dict[str, str]:
        context = context_for(request, authorization, Permission.VIEW)
        draft = store.lookup_portal_receipt(binding_for(context, handoff_id))
        if draft is None:
            raise HTTPException(status_code=404, detail="Portal receipt not found.")
        if (
            draft.receipt_binding is None
            or draft.receipt_binding.snapshot_version != snapshot_version
        ):
            raise HTTPException(status_code=409, detail="Handoff snapshot conflict.")
        response.headers["Cache-Control"] = "no-store"
        # The short-lived capability is view-only. Never put a service bearer in the browser/URL.
        return {
            "draft_id": draft.draft_id,
            "handoff_token": issue_handoff_token(
                draft.draft_id, secret=service._resolve_handoff_secret_or_503()
            ),
        }

    @app.post("/portal/handoff/receipt")
    async def open_receipt(request: Request) -> Response:
        # POST body keeps this view-only capability out of browser history and referrers.
        body = await request.body()
        if len(body) > 4096:
            raise HTTPException(
                status_code=413, detail="Handoff capability is too large."
            )
        values = parse_qs(body.decode(), keep_blank_values=True)
        token = values.get("handoff_token", [""])[-1]
        secret = service._resolve_handoff_secret_or_503()
        draft_id = verify_handoff_token(token, secret=secret)
        if draft_id is None or store.lookup_portal_draft(draft_id) is None:
            raise HTTPException(
                status_code=401, detail="Handoff session is invalid or expired."
            )
        response = RedirectResponse(
            url=request.url_for("portal_review_detail", draft_id=draft_id),
            status_code=303,
        )
        response.headers["Cache-Control"] = "no-store"
        service._set_handoff_cookie(response, request, token)
        return response


def register_portal_submission_route(
    app: FastAPI, proposal_store: PlannerProposalStore
) -> None:
    """Keep the existing authenticated browser submission on the receipt-aware store."""

    from . import http_service as service

    @app.post("/portal/review/{draft_id}/submit", response_class=HTMLResponse)
    def portal_submit_request(
        request: Request,
        draft_id: str,
        authorization: str | None = Header(default=None),
    ) -> HTMLResponse:
        auth_context = service._authorize_request(
            authorization,
            required_permission=Permission.CREATE,
            route=service._route_identifier(request),
        )
        draft = proposal_store.lookup_portal_draft(draft_id)
        if draft is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No portal draft found for '{draft_id}'.",
            )
        authorize_draft_owner(draft, auth_context)
        review = service.portal_review_state_for_persisted_draft(
            draft,
            proposal_store,
            required_fields=service._PORTAL_REQUIRED_FIELDS,
            canonical_payload_builder=service._canonical_payload_from_answers,
        )
        if (
            review.trip_plan is None
            or review.missing_fields
            or review.validation_errors
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="; ".join(review.validation_errors)
                or "Complete the request review before submitting the portal draft.",
            )
        if review.policy_blocking_codes:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": "Portal proposal submission blocked by policy verdict.",
                    "blocking_codes": review.policy_blocking_codes,
                },
            )
        submission_request = PlannerProposalSubmissionRequest(
            trip_id=review.trip_plan.trip_id,
            proposal_id=f"{review.trip_plan.trip_id.lower()}-portal-request",
            proposal_version=(
                f"portal-v1:{draft_id}" if draft.receipt_binding else "portal-v1"
            ),
            payload={
                "channel": "workflow-portal",
                "draft_id": draft_id,
                "review_surface": "browser",
            },
        )
        submission_response, manager_review = proposal_store.complete_portal_submission(
            review, submission_request
        )
        review = service.portal_review_state_for_persisted_draft(
            draft,
            proposal_store,
            required_fields=service._PORTAL_REQUIRED_FIELDS,
            canonical_payload_builder=service._canonical_payload_from_answers,
            submission_response=submission_response,
            manager_review=manager_review,
        )
        return service._TEMPLATES.TemplateResponse(
            request=request,
            name="review_summary.html",
            context=service._portal_template_context(
                request,
                review,
                auth_context=auth_context,
                exceptions=proposal_store.list_exception_requests(draft_id),
            ),
        )


def authorize_portal_view(
    request: Request,
    authorization: str | None,
    *,
    draft_id: str,
) -> PlannerAuthContext:
    from . import http_service as service

    if authorization is None:
        handoff_context = service._handoff_view_context(request, draft_id)
        if handoff_context is not None:
            return handoff_context
    context = service._authorize_request(
        authorization,
        required_permission=Permission.VIEW,
        route=service._route_identifier(request),
    )
    draft = request.app.state.proposal_store.lookup_portal_draft(draft_id)
    if draft is not None:
        authorize_draft_owner(draft, context)
    return context
