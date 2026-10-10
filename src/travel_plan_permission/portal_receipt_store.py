"""Persist owner-bound portal receipts under the existing store operation coordinator."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from fastapi import HTTPException

from .http_contract_models import PortalDraft, PortalReceiptBinding
from .persistence.operations import (
    serialized_store_operation as _serialized_store_operation,
)
from .policy_api import (
    PlannerProposalOperationResponse,
    PlannerProposalSubmissionRequest,
)
from .portal_receipts import PortalReceipt, receipt_for
from .portal_review import PortalReviewState
from .review_workflow import ReviewRequest

if TYPE_CHECKING:
    from .http_service import PlannerProposalStore


class PortalReceiptStoreMixin:
    """Receipt-specific behavior without growing the legacy HTTP/store module."""

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
                raise HTTPException(
                    status_code=409, detail="Handoff snapshot conflict."
                )
            return existing
        return store.save_portal_draft(answers, receipt_binding=binding)

    @_serialized_store_operation
    def lookup_portal_receipt(
        self, binding: PortalReceiptBinding
    ) -> PortalDraft | None:
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
    ) -> tuple[PlannerProposalOperationResponse, ReviewRequest]:
        """Coordinate submission retries with manager decisions across app instances."""

        from . import http_service as service

        store = cast("PlannerProposalStore", self)

        draft = store.lookup_portal_draft(review.draft_id)
        if draft is None or review.trip_plan is None:
            raise ValueError("A persisted valid portal draft is required.")
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
        store.record_submission(review.trip_plan, submission_request, response)
        store.record_portal_submission(draft.draft_id, response)
        return response, store.create_manager_review(review)
