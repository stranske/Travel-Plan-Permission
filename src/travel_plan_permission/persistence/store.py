"""Portal state store protocol shared by JSON, SQLite, and Postgres backends."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

# Top-level snapshot keys produced by ``PlannerProposalStore._serialize_state``
# that the SQL backends store as keyed records, one row per id. Adding a new
# mapping namespace means listing it here so ``save_snapshot`` knows to expand
# it instead of writing it as a singleton blob.
RECORD_NAMESPACES: tuple[str, ...] = (
    "plans_by_trip_id",
    "proposals_by_execution_id",
    "portal_drafts_by_id",
    "manager_reviews",
    "exception_requests_by_draft_id",
)


@runtime_checkable
class PortalStateStore(Protocol):
    """Persistence backend for the planner HTTP service portal state.

    Implementations must be safe to construct in a per-process model where
    multiple processes share the same backing store (e.g. a SQLite file or a
    Postgres database). ``save_snapshot`` should be transactional so that
    concurrent writers serialize at the storage layer and per-record changes
    survive across processes.
    """

    def initialize(self) -> None:
        """Create schema and prepare the backend for use."""

    def load_snapshot(self) -> dict[str, object] | None:
        """Return the most recent snapshot, or ``None`` if no state exists.

        The returned mapping mirrors the shape produced by
        ``PlannerProposalStore._serialize_state``.
        """

    def save_snapshot(self, snapshot: dict[str, object]) -> None:
        """Persist a serialized snapshot.

        Implementations should perform per-record upserts (within a single
        transaction) for the namespaces declared in :data:`RECORD_NAMESPACES`
        so two processes writing different ids do not clobber each other's
        rows. Singleton mappings (e.g. ``review_ids_by_draft_id``) may be
        stored as a single blob.
        """

    def close(self) -> None:
        """Release any underlying connections or file handles."""
