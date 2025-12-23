"""Snapshot capture and re-check utilities for validation results.

This module provides tamper-evident snapshots of validation runs that can be
stored immutably and replayed against newer policy versions for audit and
regression checks.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .validation import PolicyValidator, ValidationResult

if TYPE_CHECKING:
    from .models import TripPlan


def _hash_payload(payload: Mapping[str, object]) -> str:
    """Return a stable SHA-256 digest for the provided payload."""

    serialized = json.dumps(
        payload,
        default=str,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(serialized).hexdigest()


def policy_version_hash(source: PolicyValidator | Sequence[ValidationResult]) -> str:
    """Compute a deterministic hash for a policy configuration or result set."""

    if isinstance(source, PolicyValidator):
        rules_payload = [rule.model_dump(mode="json") for rule in source.rules]
        payload: dict[str, object] = {"rules": rules_payload}
    else:
        payload = {"results": [result.model_dump(mode="json") for result in source]}
    return _hash_payload(payload)


class ValidationSnapshot(BaseModel):
    """Immutable snapshot of a single validation run."""

    trip_id: str = Field(..., description="Unique trip identifier")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When the snapshot was captured",
    )
    policy_version: str = Field(..., description="Version hash of the policy set")
    input_data: dict[str, object] = Field(
        ..., description="Serialized trip plan input used for validation"
    )
    results: list[ValidationResult] = Field(
        ..., description="Validation results produced by the policy engine"
    )
    previous_hash: str | None = Field(
        default=None,
        description="Chain hash of the previous snapshot for tamper evidence",
    )
    snapshot_hash: str | None = Field(
        default=None, description="Digest of this snapshot's content"
    )
    chain_hash: str | None = Field(
        default=None,
        description=(
            "Hash derived from the previous link and the current snapshot hash to"
            " form an immutable chain"
        ),
    )

    model_config = ConfigDict(frozen=True)

    @model_validator(mode="after")
    def _set_hashes(self) -> ValidationSnapshot:
        payload = {
            "trip_id": self.trip_id,
            "timestamp": self.timestamp.isoformat(),
            "policy_version": self.policy_version,
            "input_data": self.input_data,
            "results": [result.model_dump(mode="json") for result in self.results],
            "previous_hash": self.previous_hash,
        }
        content_hash = _hash_payload(payload)
        chain_input = f"{self.previous_hash or ''}{content_hash}"
        chain_hash = sha256(chain_input.encode("utf-8")).hexdigest()

        object.__setattr__(self, "snapshot_hash", content_hash)
        object.__setattr__(self, "chain_hash", chain_hash)
        return self


class ValidationDelta(BaseModel):
    """Difference between two validation runs for a single rule."""

    rule_code: str
    original: ValidationResult | None
    rechecked: ValidationResult | None

    def changed(self) -> bool:
        """Return True when there is a substantive change in the rule outcome."""

        if self.original is None or self.rechecked is None:
            return True
        signature = (
            self.original.severity,
            self.original.message,
            self.original.blocking,
        )
        re_signature = (
            self.rechecked.severity,
            self.rechecked.message,
            self.rechecked.blocking,
        )
        return signature != re_signature


class ValidationComparison(BaseModel):
    """Structured comparison between original and re-checked results."""

    changed: list[ValidationDelta]
    unchanged: list[ValidationDelta]

    def has_differences(self) -> bool:
        """Return True when any rules changed outcome."""

        return any(delta.changed() for delta in self.changed)


class ValidationSnapshotStore:
    """Append-only storage for validation snapshots."""

    def __init__(self, base_path: str | Path | None = None):
        default_root = Path(os.getenv("SNAPSHOT_DIR", Path.cwd() / "snapshots"))
        self.base_path = Path(base_path) if base_path is not None else default_root
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _trip_path(self, trip_id: str) -> Path:
        return self.base_path / trip_id

    def last_chain_hash(self, trip_id: str) -> str | None:
        snapshots = self.load_trip_snapshots(trip_id)
        if not snapshots:
            return None
        return snapshots[-1].chain_hash

    def load_trip_snapshots(self, trip_id: str) -> list[ValidationSnapshot]:
        trip_path = self._trip_path(trip_id)
        if not trip_path.exists():
            return []
        snapshots: list[ValidationSnapshot] = []
        for path in sorted(trip_path.glob("*.json")):
            snapshots.append(self.load_snapshot(path))
        return snapshots

    def load_snapshot(self, path: str | Path) -> ValidationSnapshot:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return ValidationSnapshot.model_validate(data)

    def append(self, snapshot: ValidationSnapshot) -> Path:
        trip_path = self._trip_path(snapshot.trip_id)
        trip_path.mkdir(parents=True, exist_ok=True)
        filename = f"{snapshot.timestamp.isoformat().replace(':', '-')}.json"
        target = trip_path / filename
        serialized = snapshot.model_dump(mode="json")
        payload = json.dumps(serialized, separators=(",", ":"), sort_keys=True)
        if len(payload.encode("utf-8")) > 10_240:
            msg = "Snapshot exceeds 10KB; reduce payload size or adjust snapshot fields"
            raise ValueError(msg)
        # Immutable writes: refuse to overwrite an existing snapshot.
        with target.open("x", encoding="utf-8") as handle:
            handle.write(payload)
        return target

    def recheck(
        self,
        snapshot: ValidationSnapshot,
        validator: PolicyValidator,
    ) -> tuple[list[ValidationResult], ValidationComparison]:
        """Re-run validation using stored inputs and compare results."""

        from .models import TripPlan  # Local import to avoid circular dependency

        plan = TripPlan.model_validate(snapshot.input_data)
        rechecked_results = validator.validate_plan(plan)
        comparison = compare_results(snapshot.results, rechecked_results)
        return rechecked_results, comparison


def compare_results(
    original: Iterable[ValidationResult],
    rechecked: Iterable[ValidationResult],
) -> ValidationComparison:
    """Compare validation outputs and return a structured diff."""

    original_map = {result.code: result for result in original}
    rechecked_map = {result.code: result for result in rechecked}

    changed: list[ValidationDelta] = []
    unchanged: list[ValidationDelta] = []

    for code, original_result in original_map.items():
        rechecked_result = rechecked_map.get(code)
        delta = ValidationDelta(
            rule_code=code, original=original_result, rechecked=rechecked_result
        )
        if delta.changed():
            changed.append(delta)
        else:
            unchanged.append(delta)

    for code, rechecked_result in rechecked_map.items():
        if code in original_map:
            continue
        changed.append(
            ValidationDelta(rule_code=code, original=None, rechecked=rechecked_result)
        )

    return ValidationComparison(changed=changed, unchanged=unchanged)


def snapshot_from_plan(
    plan: TripPlan,
    *,
    results: list[ValidationResult],
    policy_version: str,
    previous_hash: str | None = None,
) -> ValidationSnapshot:
    """Capture an immutable snapshot from the given plan and validation results."""

    return ValidationSnapshot(
        trip_id=plan.trip_id,
        timestamp=datetime.now(UTC),
        policy_version=policy_version,
        input_data=plan.model_dump(mode="json"),
        results=results,
        previous_hash=previous_hash,
    )
