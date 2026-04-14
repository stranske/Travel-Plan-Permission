"""Runnable HTTP service for the planner-facing policy API."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from importlib import resources
from typing import Annotated, Any

import uvicorn
from fastapi import Body, FastAPI, HTTPException
from pydantic import BaseModel

from .models import TripPlan
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

REQUIRED_PLANNER_CONFIG = (
    "TPP_BASE_URL",
    "TPP_ACCESS_TOKEN",
    "TPP_OIDC_PROVIDER",
)


def _load_demo_trip_plan() -> TripPlan:
    raw = (
        resources.files("travel_plan_permission.config")
        .joinpath("planner_service_demo_trip.json")
        .read_text(encoding="utf-8")
    )
    return TripPlan.model_validate_json(raw)


@dataclass
class PlannerServiceStore:
    """In-memory trip-plan store for planner-facing live testing."""

    trip_plans: dict[str, TripPlan] = field(default_factory=dict)

    @classmethod
    def with_demo_seed(cls) -> PlannerServiceStore:
        store = cls()
        demo_plan = _load_demo_trip_plan()
        store.trip_plans[demo_plan.trip_id] = demo_plan
        return store

    def save_trip_plan(self, plan: TripPlan) -> None:
        self.trip_plans[plan.trip_id] = plan

    def get_trip_plan(self, trip_id: str) -> TripPlan:
        plan = self.trip_plans.get(trip_id)
        if plan is None:
            raise KeyError(trip_id)
        return plan


class ProposalSubmissionEnvelope(BaseModel):
    """HTTP request body for proposal submission."""

    trip_plan: TripPlan
    request: PlannerProposalSubmissionRequest


class ReadinessResponse(BaseModel):
    """Readiness status for the planner-facing service."""

    ok: bool
    missing_config: list[str]
    seeded_trip_ids: list[str]


def _missing_runtime_config() -> list[str]:
    return [name for name in REQUIRED_PLANNER_CONFIG if not os.getenv(name)]


def create_app(store: PlannerServiceStore | None = None) -> FastAPI:
    """Create the planner-facing HTTP application."""

    planner_store = store or PlannerServiceStore.with_demo_seed()
    app = FastAPI(
        title="Travel Plan Permission Planner Service",
        version="0.1.0",
        description="Thin HTTP wrapper around the planner-facing policy API.",
    )
    app.state.planner_store = planner_store

    @app.get("/healthz")
    def healthcheck() -> dict[str, Any]:
        return {
            "ok": True,
            "service": "travel-plan-permission",
            "planner_routes": [
                "/api/planner/policy-snapshot",
                "/api/planner/proposals",
                "/api/planner/proposals/{proposal_id}/executions/{execution_id}",
                "/api/planner/executions/{execution_id}/evaluation-result",
            ],
        }

    @app.get("/readyz", response_model=ReadinessResponse)
    def readiness() -> ReadinessResponse:
        missing = _missing_runtime_config()
        response = ReadinessResponse(
            ok=not missing,
            missing_config=missing,
            seeded_trip_ids=sorted(planner_store.trip_plans),
        )
        if missing:
            raise HTTPException(status_code=503, detail=response.model_dump(mode="json"))
        return response

    @app.get("/api/planner/policy-snapshot", response_model=PlannerPolicySnapshot)
    def planner_policy_snapshot(
        request: Annotated[PlannerPolicySnapshotRequest, Body(...)],
    ) -> PlannerPolicySnapshot:
        try:
            plan = planner_store.get_trip_plan(request.trip_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail=(
                    "No planner trip is loaded for "
                    f"{request.trip_id!r}. Submit the trip first or use the seeded "
                    "demo trip id TRIP-PLANNER-2001."
                ),
            ) from exc
        return get_policy_snapshot(plan, request=request)

    @app.post(
        "/api/planner/proposals",
        response_model=PlannerProposalOperationResponse,
        status_code=202,
    )
    def planner_proposal_submission(
        envelope: ProposalSubmissionEnvelope,
    ) -> PlannerProposalOperationResponse:
        planner_store.save_trip_plan(envelope.trip_plan)
        try:
            return submit_proposal(envelope.trip_plan, envelope.request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get(
        "/api/planner/proposals/{proposal_id}/executions/{execution_id}",
        response_model=PlannerProposalOperationResponse,
    )
    def planner_execution_status(
        proposal_id: str,
        execution_id: str,
        request: Annotated[PlannerProposalStatusRequest, Body(...)],
    ) -> PlannerProposalOperationResponse:
        if request.proposal_id != proposal_id or request.execution_id != execution_id:
            raise HTTPException(
                status_code=400,
                detail="Route parameters must match the status request payload.",
            )
        try:
            plan = planner_store.get_trip_plan(request.trip_id)
            return poll_execution_status(plan, request)
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail=f"No stored planner trip for {request.trip_id!r}.",
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get(
        "/api/planner/executions/{execution_id}/evaluation-result",
        response_model=PlannerProposalEvaluationResult,
    )
    def planner_evaluation_result(
        execution_id: str,
        request: Annotated[PlannerProposalEvaluationRequest, Body(...)],
    ) -> PlannerProposalEvaluationResult:
        if request.execution_id != execution_id:
            raise HTTPException(
                status_code=400,
                detail="Route parameters must match the evaluation request payload.",
            )
        try:
            plan = planner_store.get_trip_plan(request.trip_id)
            return get_evaluation_result(plan, request)
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail=f"No stored planner trip for {request.trip_id!r}.",
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app


app = create_app()


def main() -> None:
    """Run the planner-facing HTTP service with uvicorn."""

    uvicorn.run(
        "travel_plan_permission.planner_service:app",
        host=os.getenv("TPP_SERVICE_HOST", "127.0.0.1"),
        port=int(os.getenv("TPP_SERVICE_PORT", "8000")),
        reload=False,
    )
