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
    "trip_states_by_execution_id",
    "portal_drafts_by_id",
    "expense_drafts_by_id",
    "manager_reviews",
    "review_ids_by_draft_id",
    "exception_requests_by_draft_id",
)


@runtime_checkable
class PortalStateStore(Protocol):
    """Persistence backend for the planner HTTP service portal state.

    Implementations must be safe to construct in a per-process model where
    multiple processes share the same backing store (e.g. a SQLite file or a
    Postgres database). ``save_snapshot`` should be transactional so that
    concurrent writers serialize at the storage layer and per-record changes
    survive across processes when saving independent keyed records with
    ``replace=False``. Full replacement requires one authoritative writer per
    namespace: a stale complete snapshot can otherwise delete another writer's
    records. SQL-backed PlannerProposalStore coordinates its whole operation
    separately, refreshing before mutations and retaining the guard across data
    commits. Direct snapshot writers must not bypass that service boundary.
    """

    def initialize(self) -> None:
        """Create schema and prepare the backend for use."""

    def load_snapshot(self) -> dict[str, object] | None:
        """Return the most recent snapshot, or ``None`` if no state exists.

        The returned mapping mirrors the shape produced by
        ``PlannerProposalStore._serialize_state``.
        """

    def save_snapshot(self, snapshot: dict[str, object], *, replace: bool = False) -> None:
        """Persist a serialized snapshot.

        Mapped namespaces are merged per record by default so independent
        writers cannot delete records they did not read.  Callers that own the
        complete authoritative namespace, such as LRU eviction, pass
        ``replace=True`` to remove rows absent from the snapshot. Lists such as audit events remain singleton payloads; review indexes
        are keyed records.
        """

    def close(self) -> None:
        """Release any underlying connections or file handles."""
