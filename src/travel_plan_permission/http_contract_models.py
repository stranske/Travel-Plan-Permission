"""HTTP adapter data models and runtime configuration facade."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from .models import ExceptionRequest, ExpenseReport, TripPlan
from .planner_auth import PlannerAuthConfig
from .policy_api import (
    PlannerPolicySnapshotRequest,
    PlannerProposalOperationResponse,
    PlannerProposalSubmissionRequest,
)
from .portal_review import PortalArtifact
from .receipts import ReceiptExtractionResult
from .security import Permission, RoleName


@dataclass(frozen=True)
class PortalDraft:
    """Stored portal draft answers for request review and submission."""

    draft_id: str
    answers: dict[str, object]
    updated_at: datetime
    cached_artifacts: dict[str, PortalArtifact] = field(default_factory=dict)
    submission_response: PlannerProposalOperationResponse | None = None


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

    @property
    def can_configure(self) -> bool:
        """Return whether this simulated role view exposes admin diagnostics."""

        return self.role in {
            RoleName.FINANCE_ADMIN,
            RoleName.POLICY_ADMIN,
            RoleName.SYSTEM_ADMIN,
        }


@dataclass(frozen=True)
class ExpensePortalReviewState:
    """Computed expense portal review context derived from a draft."""

    draft_id: str
    answers: dict[str, object]
    missing_fields: list[str]
    validation_errors: list[str]
    receipt_state: str
    receipt_extraction: ReceiptExtractionResult | None
    expense_report: ExpenseReport | None
    review_warnings: list[str]
    artifacts: dict[str, PortalArtifact]


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
    oidc_audience_configured: bool = Field(default=False)
    oidc_role_map_configured: bool = Field(default=False)
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
            oidc_audience_configured=bool(config.oidc_audience),
            oidc_role_map_configured=config.oidc_role_map_configured,
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
            + "). Supported auth modes: static-token, bootstrap-token, oidc. "
            + "Supported TPP_OIDC_PROVIDER values: azure_ad, okta, google."
        )


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
