"""Planner-facing HTTP service for local and preview integration testing."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import UTC, datetime

import uvicorn
from fastapi import Body, FastAPI, Header, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from .models import TripPlan
from .planner_auth import PlannerAuthConfig, authenticate_request
from .policy_api import (
    PlannerPolicySnapshot,
    PlannerPolicySnapshotRequest,
    PlannerProposalEvaluationRequest,
    PlannerProposalEvaluationResult,
    PlannerProposalOperationResponse,
    PlannerProposalStatusRequest,
    PlannerProposalSubmissionRequest,
    get_evaluation_result,
    get_policy_snapshot,
    poll_execution_status,
    submit_proposal,
)
from .security import Permission

_OPTIONAL_SNAPSHOT_BODY = Body(default=None)


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
        response: Response,
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
        readiness = _readiness_response()
        if readiness.status != "ready":
            response.headers["x-tpp-readiness"] = "misconfigured"
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
    PlannerRuntimeConfig.from_env().ensure_valid()
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
