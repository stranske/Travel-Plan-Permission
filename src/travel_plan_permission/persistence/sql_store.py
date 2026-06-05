"""Shared SQL snapshot-store control flow."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from typing import Any

from .store import RECORD_NAMESPACES, PortalStateStore


class SqlSnapshotStore(PortalStateStore, ABC):
    """Base class for SQL stores that reconcile mapped namespaces per record."""

    def load_snapshot(self) -> dict[str, object] | None:
        records, singletons = self._select_all()
        if not records and not singletons:
            return None

        snapshot: dict[str, Any] = {namespace: {} for namespace in RECORD_NAMESPACES}
        for namespace, record_key, payload in records:
            snapshot.setdefault(namespace, {})[record_key] = self._coerce_payload(payload)
        for namespace, payload in singletons:
            snapshot[namespace] = self._coerce_payload(payload)
        return snapshot

    def save_snapshot(self, snapshot: dict[str, object]) -> None:
        now = self._now()
        with self._transaction() as handle:
            for namespace, value in snapshot.items():
                if namespace in RECORD_NAMESPACES and isinstance(value, dict):
                    record_keys = [str(record_key) for record_key in value]
                    self._delete_absent_records(handle, namespace, record_keys)
                    for record_key, payload in value.items():
                        self._upsert_record(handle, namespace, str(record_key), payload, now)
                else:
                    self._upsert_singleton(handle, namespace, value, now)

    @abstractmethod
    def _select_all(self) -> tuple[list[tuple[str, str, object]], list[tuple[str, object]]]:
        """Return all per-record and singleton rows."""

    @abstractmethod
    def _transaction(self) -> AbstractContextManager[Any]:
        """Return a write transaction context whose value is passed to SQL hooks."""

    @abstractmethod
    def _delete_absent_records(self, handle: Any, namespace: str, record_keys: list[str]) -> None:
        """Delete rows in ``namespace`` whose keys are absent from ``record_keys``."""

    @abstractmethod
    def _upsert_record(
        self,
        handle: Any,
        namespace: str,
        record_key: str,
        payload: object,
        updated_at: object,
    ) -> None:
        """Insert or update a per-record payload."""

    @abstractmethod
    def _upsert_singleton(
        self,
        handle: Any,
        namespace: str,
        payload: object,
        updated_at: object,
    ) -> None:
        """Insert or update a singleton payload."""

    @abstractmethod
    def _now(self) -> object:
        """Return a backend-compatible timestamp value."""

    def _coerce_payload(self, value: object) -> object:
        if isinstance(value, (dict, list)):
            return value
        if isinstance(value, (str, bytes, bytearray)):
            return json.loads(value)
        return value
