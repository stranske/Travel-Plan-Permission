"""Persist owner-bound portal receipts under the existing store operation coordinator."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, cast

from fastapi import HTTPException

from .http_contract_models import PortalDraft, PortalReceiptBinding, StoredProposal
from .models import TripPlan
from .persistence.operations import (
    serialized_store_operation as _serialized_store_operation,
)
from .planner_auth import PlannerAuthContext
from .policy_api import (
    PlannerProposalOperationResponse,
    PlannerProposalSubmissionRequest,
)
from .portal_receipts import PortalReceipt, authorize_draft_owner, receipt_for
from .portal_review import PortalReviewState
from .review_workflow import ReviewRequest

if TYPE_CHECKING:
    from .http_service import PlannerProposalStore


class PortalReceiptStoreMixin:
    """Receipt-specific behavior without growing the legacy HTTP/store module."""

    @_serialized_store_operation
    def lookup_execution_draft(self, execution_id: str) -> PortalDraft | None:
        """Resolve linkage from persisted portal state, never a caller's payload."""

        store = cast("PlannerProposalStore", self)
        matches = [
            draft
            for draft in store.portal_drafts_by_id.values()
            if draft.submission_response is not None
            and draft.submission_response.result_payload.get("execution_id") == execution_id
        ]
        if len(matches) > 1:
            raise HTTPException(status_code=409, detail="Submitted portal snapshot conflict.")
        if matches:
            return matches[0]
        stored = store.lookup_submission(execution_id)
        # Receipt-bound submissions use a reserved version prefix. Free-form
        # caller payload keys do not establish portal linkage.
        if stored is not None and stored.request.proposal_version.startswith("portal-v1:"):
            raise HTTPException(status_code=404, detail="Portal receipt not found.")
        return None

    def preserve_bound_submission(
        self,
        execution_id: str,
        trip_plan: TripPlan,
        request: PlannerProposalSubmissionRequest,
        *,
        portal_resubmission: bool = False,
        auth_context: PlannerAuthContext | None = None,
    ) -> bool:
        """Keep bound snapshots immutable inside record_submission's lock."""

        store = cast("PlannerProposalStore", self)
        draft = store.lookup_execution_draft(execution_id)
        if draft is not None:
            if draft.receipt_binding is not None:
                if auth_context is None:
                    raise HTTPException(status_code=404, detail="Portal receipt not found.")
                authorize_draft_owner(draft, auth_context)
            if portal_resubmission and draft.receipt_binding is None:
                return False  # Only the legacy portal can resubmit its mutable drafts.
            prior = store.lookup_submission(execution_id)
            if prior is None or prior.trip_plan != trip_plan or prior.request != request:
                raise HTTPException(status_code=409, detail="Submitted portal snapshot conflict.")
            return True
        return False

    @_serialized_store_operation
    def lookup_execution_projection(
        self, execution_id: str, *, auth_context: PlannerAuthContext
    ) -> tuple[StoredProposal, PortalDraft | None] | None:
        """Return a submission with the authoritative manager decision applied.

        The submitted snapshot stays immutable; only the decision state
        (``status`` and attributed ``approval_history``) is read from the manager
        review, and the draft's exception requests from the draft-keyed policy
        store, for the draft bound to this execution.  Draft, submission
        and review are read under one store operation so a concurrent decision
        cannot be observed half-applied.
        """

        store = cast("PlannerProposalStore", self)
        stored = store.lookup_submission(execution_id)
        if stored is None:
            return None
        draft = store.lookup_execution_draft(execution_id)
        if draft is None:
            return stored, None
        authorize_draft_owner(draft, auth_context)
        latest = draft.submission_response
        bound_execution = latest.result_payload.get("execution_id") if latest is not None else None
        if bound_execution != execution_id:
            return stored, draft
        projected = stored.trip_plan.model_copy(deep=True)
        # Exception requests are keyed by draft, not carried by the snapshot.
        projected.exception_requests = store.list_exception_requests(draft.draft_id)
        review = store.lookup_manager_review_for_draft(draft.draft_id)
        if review is not None and review.trip_plan.trip_id == stored.trip_plan.trip_id:
            # Only workflow-owned fields may differ from the reviewed snapshot.
            mutable = {"status", "approval_history", "exception_requests"}
            if review.trip_plan.model_dump(exclude=mutable) != stored.trip_plan.model_dump(
                exclude=mutable
            ):
                raise HTTPException(status_code=409, detail="Submitted portal snapshot conflict.")
            projected.status = review.trip_plan.status
            projected.approval_history = tuple(
                event.model_copy(deep=True) for event in review.trip_plan.approval_history
            )
        return replace(stored, trip_plan=projected), draft

    @_serialized_store_operation
    def prepare_portal_receipt(
        self, answers: dict[str, object], binding: PortalReceiptBinding
    ) -> PortalDraft:
        """Atomically deduplicate one immutable owner-scoped handoff snapshot."""

        store = cast("PlannerProposalStore", self)

        existing = store.lookup_portal_receipt(binding)
        if existing is not None:
            prior = existing.receipt_binding
            if prior is None or (
                prior.snapshot_version != binding.snapshot_version
                or prior.snapshot_sha256 != binding.snapshot_sha256
            ):
                raise HTTPException(status_code=409, detail="Handoff snapshot conflict.")
            return existing
        return store.save_portal_draft(answers, receipt_binding=binding)

    @_serialized_store_operation
    def lookup_portal_receipt(self, binding: PortalReceiptBinding) -> PortalDraft | None:
        """Find a receipt only within the authenticated caller's identity scope."""

        store = cast("PlannerProposalStore", self)

        for draft in store.portal_drafts_by_id.values():
            prior = draft.receipt_binding
            if prior is not None and (
                prior.owner_mode,
                prior.owner_provider,
                prior.owner_subject,
                prior.owner_namespace,
                prior.handoff_id,
            ) == (
                binding.owner_mode,
                binding.owner_provider,
                binding.owner_subject,
                binding.owner_namespace,
                binding.handoff_id,
            ):
                return store.lookup_portal_draft(draft.draft_id)
        return None

    @_serialized_store_operation
    def read_portal_receipt(
        self, binding: PortalReceiptBinding, snapshot_version: str
    ) -> PortalReceipt:
        """Read draft and manager state under one cross-instance operation lock."""

        store = cast("PlannerProposalStore", self)

        draft = store.lookup_portal_receipt(binding)
        if draft is None:
            raise HTTPException(status_code=404, detail="Portal receipt not found.")
        if (
            draft.receipt_binding is None
            or draft.receipt_binding.snapshot_version != snapshot_version
        ):
            raise HTTPException(status_code=409, detail="Handoff snapshot conflict.")
        return receipt_for(draft, store.lookup_manager_review_for_draft(draft.draft_id))

    @_serialized_store_operation
    def complete_portal_submission(
        self,
        review: PortalReviewState,
        submission_request: PlannerProposalSubmissionRequest,
        *,
        auth_context: PlannerAuthContext | None = None,
    ) -> tuple[PlannerProposalOperationResponse, ReviewRequest]:
        """Coordinate submission retries with manager decisions across app instances."""

        from . import http_service as service

        store = cast("PlannerProposalStore", self)

        draft = store.lookup_portal_draft(review.draft_id)
        if draft is None or review.trip_plan is None:
            raise ValueError("A persisted valid portal draft is required.")
        if draft.receipt_binding is not None:
            if auth_context is None:
                raise HTTPException(status_code=404, detail="Portal receipt not found.")
            authorize_draft_owner(draft, auth_context)
        manager_review = store.lookup_manager_review_for_draft(review.draft_id)
        if draft.receipt_binding and draft.submission_response and manager_review:
            return draft.submission_response, manager_review
        response = service.submit_proposal(review.trip_plan, submission_request)
        if draft.receipt_binding and response.submission_status in {
            "failed",
            "unavailable",
        }:
            raise HTTPException(
                status_code=503 if response.submission_status == "unavailable" else 409,
                detail="Portal proposal submission was not accepted.",
            )
        store.record_submission(
            review.trip_plan,
            submission_request,
            response,
            portal_resubmission=True,
            auth_context=auth_context,
        )
        store.record_portal_submission(draft.draft_id, response)
        return response, store.create_manager_review(review)
