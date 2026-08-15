"""Planner-facing readiness and API route group."""

from __future__ import annotations

from typing import Any

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

from .http_contract_models import (
    PlannerPolicySnapshotHttpRequest,
    PlannerProposalSubmissionHttpRequest,
    PlannerReadinessResponse,
)
from .intake_requirements import (
    PlannerIntakeRequirementCatalog,
    get_intake_requirement_catalog,
)
from .models import TripPlan
from .policy_api import (
    PlannerPolicySnapshot,
    PlannerPolicySnapshotRequest,
    PlannerProposalEvaluationResult,
    PlannerProposalOperationResponse,
    get_evaluation_result,
    get_policy_snapshot,
    poll_execution_status,
    submit_proposal,
)
from .security import Permission

_OPTIONAL_SNAPSHOT_BODY = Body(default=None)


def register_planner_api_routes(app: FastAPI, proposal_store: Any) -> None:
    """Register readiness and planner API endpoints."""

    # Imported lazily to avoid a cycle while http_service assembles the app.
    from . import http_service as service

    _authorize_request = service._authorize_request
    _evaluation_request = service._evaluation_request
    _readiness_response = service._readiness_response
    _route_identifier = service._route_identifier
    _submission_status_request = service._submission_status_request

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

    @app.get(
        "/api/planner/intake-requirements",
        response_model=PlannerIntakeRequirementCatalog,
    )
    def intake_requirements(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> PlannerIntakeRequirementCatalog:
        _authorize_request(
            authorization,
            required_permission=Permission.VIEW,
            route=_route_identifier(request),
        )
        return get_intake_requirement_catalog()

    @app.get("/api/planner/policy-snapshot", response_model=PlannerPolicySnapshot)
    def policy_snapshot(
        request: Request,
        trip_id: str | None = Query(default=None),
        request_body: PlannerPolicySnapshotHttpRequest | None = _OPTIONAL_SNAPSHOT_BODY,
        authorization: str | None = Header(default=None),
    ) -> PlannerPolicySnapshot:
        _authorize_request(
            authorization,
            required_permission=Permission.VIEW,
            route=_route_identifier(request),
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
        request: Request,
        payload: PlannerProposalSubmissionHttpRequest,
        authorization: str | None = Header(default=None),
    ) -> PlannerProposalOperationResponse:
        _authorize_request(
            authorization,
            required_permission=Permission.CREATE,
            route=_route_identifier(request),
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
        request: Request,
        proposal_id: str,
        execution_id: str,
        authorization: str | None = Header(default=None),
    ) -> PlannerProposalOperationResponse:
        _authorize_request(
            authorization,
            required_permission=Permission.VIEW,
            route=_route_identifier(request),
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
        request: Request,
        execution_id: str,
        authorization: str | None = Header(default=None),
    ) -> PlannerProposalEvaluationResult:
        _authorize_request(
            authorization,
            required_permission=Permission.VIEW,
            route=_route_identifier(request),
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
