"""Tests for validation snapshot capture and re-checking."""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal

import pytest

from travel_plan_permission.models import ApprovalOutcome, TripPlan
from travel_plan_permission.snapshots import (
    ValidationSnapshot,
    ValidationSnapshotStore,
    compare_results,
    policy_version_hash,
    snapshot_from_plan,
)
from travel_plan_permission.validation import (
    DurationLimitRule,
    PolicyValidator,
    ValidationResult,
    ValidationSeverity,
)


def _plan() -> TripPlan:
    return TripPlan(
        trip_id="TRIP-CHAIN",
        traveler_name="Dana Analyst",
        destination="Austin, TX",
        departure_date=date(2025, 4, 1),
        return_date=date(2025, 4, 5),
        purpose="Training",
        estimated_cost=Decimal("1200.00"),
    )


def _validator(max_days: int = 10) -> PolicyValidator:
    rule = DurationLimitRule(name="duration_limit", code="DUR-001", max_consecutive_days=max_days)
    return PolicyValidator([rule])


def test_snapshot_chain_and_recheck(tmp_path) -> None:
    validator = _validator(max_days=10)
    plan = _plan()
    results = plan.run_validation(validator=validator)

    store = ValidationSnapshotStore(base_path=tmp_path)
    first_snapshot = snapshot_from_plan(
        plan,
        results=results,
        policy_version=policy_version_hash(validator),
        previous_hash=store.last_chain_hash(plan.trip_id),
    )

    stored_path = store.append(first_snapshot)
    rechecked_results, comparison = store.recheck(first_snapshot, validator)

    assert stored_path.exists()
    assert first_snapshot.snapshot_hash is not None
    assert first_snapshot.chain_hash is not None
    assert comparison.has_differences() is False
    assert rechecked_results == results

    # Append a second snapshot to ensure chain linkage includes prior hash.
    second_snapshot = snapshot_from_plan(
        plan,
        results=results,
        policy_version=policy_version_hash(validator),
        previous_hash=store.last_chain_hash(plan.trip_id),
    )
    store.append(second_snapshot)
    assert second_snapshot.previous_hash == first_snapshot.chain_hash


def test_compare_results_flags_differences() -> None:
    original = [
        ValidationResult(
            code="ADV-001",
            message="Original message",
            severity=ValidationSeverity.ERROR,
            rule_name="advance",
            blocking=True,
        )
    ]
    rechecked = [
        ValidationResult(
            code="ADV-001",
            message="Updated policy message",
            severity=ValidationSeverity.ERROR,
            rule_name="advance",
            blocking=True,
        ),
        ValidationResult(
            code="NEW-002",
            message="New rule added",
            severity=ValidationSeverity.WARNING,
            rule_name="new_rule",
            blocking=False,
        ),
    ]

    comparison = compare_results(original, rechecked)

    assert comparison.has_differences() is True
    changed_codes = {delta.rule_code for delta in comparison.changed}
    assert changed_codes == {"ADV-001", "NEW-002"}


def test_policy_version_hash_is_stable() -> None:
    results = [
        ValidationResult(
            code="ADV-001",
            message="Message",
            severity=ValidationSeverity.ERROR,
            rule_name="advance",
            blocking=True,
        ),
        ValidationResult(
            code="DUR-001",
            message="Duration ok",
            severity=ValidationSeverity.INFO,
            rule_name="duration",
            blocking=False,
        ),
    ]

    digest_1 = policy_version_hash(results)
    digest_2 = policy_version_hash(results)
    assert digest_1 == digest_2


def test_flagged_decision_captures_snapshot_and_stays_small(tmp_path) -> None:
    validator = _validator(max_days=5)
    plan = _plan()
    plan.run_validation(validator=validator)

    store = ValidationSnapshotStore(base_path=tmp_path)
    plan.record_approval_decision(
        approver_id="approver-1",
        level="manager",
        outcome=ApprovalOutcome.FLAGGED,
        justification="Needs manual review",
        snapshot_store=store,
        validator=validator,
    )

    stored = store._trip_path(plan.trip_id).glob("*.json")
    stored_paths = list(stored)
    assert len(stored_paths) == 1
    stored_path = stored_paths[0]
    assert stored_path.stat().st_size < 10_240

    snapshots = store.load_trip_snapshots(plan.trip_id)
    assert len(snapshots) == 1
    assert snapshots[0].results == plan.validation_results


@pytest.mark.parametrize("operation", ["append", "load_trip_snapshots", "last_chain_hash"])
@pytest.mark.parametrize("escape", ["../outside", "nested/../../outside", "absolute", "symlink"])
def test_snapshot_store_rejects_trip_path_escape(tmp_path, operation, escape) -> None:
    outside = tmp_path / "outside"
    outside_store = ValidationSnapshotStore(outside)
    original = snapshot_from_plan(_plan(), results=[], policy_version="test")
    sentinel = outside_store.append(original)
    original_bytes = sentinel.read_bytes()
    store = ValidationSnapshotStore(tmp_path / "snapshots")
    if escape == "absolute":
        trip_id = str(sentinel.parent)
    elif escape == "symlink":
        (store.base_path / "escape").symlink_to(outside, target_is_directory=True)
        trip_id = "escape/TRIP-CHAIN"
    else:
        trip_id = f"{escape}/TRIP-CHAIN"
    before = sorted(outside.rglob("*"))

    with pytest.raises(ValueError, match="within snapshot store"):
        if operation == "append":
            plan = _plan().model_copy(update={"trip_id": trip_id})
            store.append(snapshot_from_plan(plan, results=[], policy_version="test"))
        else:
            getattr(store, operation)(trip_id)

    assert sentinel.read_bytes() == original_bytes
    assert sorted(outside.rglob("*")) == before
    assert not (store.base_path / "nested").exists()


@pytest.mark.parametrize("trip_id", ["", ".", "nested/.."])
def test_snapshot_store_rejects_base_directory_as_trip(tmp_path, trip_id) -> None:
    store = ValidationSnapshotStore(tmp_path)
    with pytest.raises(ValueError, match="within snapshot store"):
        store.load_trip_snapshots(trip_id)


@pytest.mark.parametrize("operation", ["load_snapshot", "load_trip_snapshots", "append"])
def test_snapshot_store_rejects_external_snapshot_and_file_symlink(tmp_path, operation) -> None:
    outside_store = ValidationSnapshotStore(tmp_path / "outside")
    snapshot = snapshot_from_plan(_plan(), results=[], policy_version="test")
    outside_path = outside_store.append(snapshot)
    original_bytes = outside_path.read_bytes()
    store = ValidationSnapshotStore(tmp_path / "snapshots")
    trip_path = store.base_path / snapshot.trip_id
    trip_path.mkdir()
    (trip_path / outside_path.name).symlink_to(outside_path)

    with pytest.raises(ValueError, match="within snapshot store"):
        if operation == "load_snapshot":
            store.load_snapshot(outside_path)
        elif operation == "append":
            store.append(snapshot)
        else:
            store.load_trip_snapshots(snapshot.trip_id)

    assert outside_path.read_bytes() == original_bytes


def test_snapshot_store_relative_root_stays_anchored_after_cwd_change(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    store = ValidationSnapshotStore("snapshots")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    snapshot = snapshot_from_plan(_plan(), results=[], policy_version="test")

    path = store.append(snapshot)

    assert path.is_relative_to(tmp_path / "snapshots")
    assert store.load_snapshot(path) == snapshot
    assert store.load_trip_snapshots(snapshot.trip_id) == [snapshot]
    assert not (elsewhere / "snapshots").exists()


@pytest.mark.parametrize("as_string", [False, True])
def test_relative_snapshot_read_uses_store_root_after_cwd_change(tmp_path, monkeypatch, as_string):
    store = ValidationSnapshotStore(tmp_path / "snapshots")
    snapshot = snapshot_from_plan(_plan(), results=[], policy_version="test")
    path = store.append(snapshot)
    relative = path.relative_to(store.base_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    assert store.load_snapshot(str(relative) if as_string else relative) == snapshot
    with pytest.raises(ValueError, match="within snapshot store"):
        store.load_snapshot("../outside.json")


def test_load_snapshot_rejects_a_tampered_payload(tmp_path) -> None:
    store = ValidationSnapshotStore(tmp_path)
    snapshot = snapshot_from_plan(_plan(), results=[], policy_version="test")
    path = store.append(snapshot)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["input_data"]["purpose"] = "Vacation in Maui"
    path.write_text(json.dumps(data), encoding="utf-8")
    tampered_bytes = path.read_bytes()

    with pytest.raises(ValueError) as error:
        store.load_snapshot(path)

    assert str(path) in str(error.value)
    assert "snapshot_hash" in str(error.value)
    assert snapshot.snapshot_hash in str(error.value)
    assert path.read_bytes() == tampered_bytes


@pytest.mark.parametrize("field", ["snapshot_hash", "chain_hash"])
def test_load_snapshot_rejects_a_tampered_hash(tmp_path, field) -> None:
    store = ValidationSnapshotStore(tmp_path)
    snapshot = snapshot_from_plan(_plan(), results=[], policy_version="test")
    path = store.append(snapshot)
    data = json.loads(path.read_text(encoding="utf-8"))
    data[field] = "0" * 64
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError) as error:
        store.load_snapshot(path)

    assert str(path) in str(error.value)
    assert field in str(error.value)
    assert data[field] in str(error.value)
    assert getattr(snapshot, field) in str(error.value)


@pytest.mark.parametrize("field", ["snapshot_hash", "chain_hash"])
@pytest.mark.parametrize("change", ["remove", "null", "empty"])
def test_load_snapshot_requires_persisted_hashes(tmp_path, field, change) -> None:
    store = ValidationSnapshotStore(tmp_path)
    path = store.append(snapshot_from_plan(_plan(), results=[], policy_version="test"))
    data = json.loads(path.read_text(encoding="utf-8"))
    if change == "remove":
        del data[field]
    else:
        data[field] = None if change == "null" else ""
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError) as error:
        store.load_snapshot(path)

    assert str(path) in str(error.value)
    assert field in str(error.value)


@pytest.mark.parametrize("recompute_hashes", [False, True])
def test_load_trip_snapshots_rejects_a_broken_chain_link(tmp_path, recompute_hashes) -> None:
    store = ValidationSnapshotStore(tmp_path)
    first = snapshot_from_plan(_plan(), results=[], policy_version="test")
    first_path = store.append(first)
    second = ValidationSnapshot(
        trip_id=first.trip_id,
        timestamp=first.timestamp + timedelta(seconds=1),
        policy_version="test",
        input_data=first.input_data,
        results=[],
        previous_hash=first.chain_hash,
    )
    second_path = store.append(second)
    data = json.loads(second_path.read_text(encoding="utf-8"))
    data["previous_hash"] = "0" * 64
    if recompute_hashes:
        # A self-consistent file must still be rejected when it links to the wrong predecessor.
        del data["snapshot_hash"]
        del data["chain_hash"]
        data = ValidationSnapshot.model_validate(data).model_dump(mode="json")
    second_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError) as error:
        store.load_trip_snapshots(first.trip_id)

    assert str(first_path) in str(error.value)
    assert str(second_path) in str(error.value)


def test_load_trip_snapshots_rejects_a_nonempty_first_link(tmp_path) -> None:
    store = ValidationSnapshotStore(tmp_path)
    snapshot = snapshot_from_plan(
        _plan(), results=[], policy_version="test", previous_hash="orphan"
    )
    path = store.append(snapshot)

    with pytest.raises(ValueError) as error:
        store.load_trip_snapshots(snapshot.trip_id)

    assert str(path) in str(error.value)
    assert "previous_hash" in str(error.value)
    assert "None" in str(error.value)


def test_snapshot_hashes_round_trip_and_chain_reload(tmp_path) -> None:
    store = ValidationSnapshotStore(tmp_path)
    first = snapshot_from_plan(_plan(), results=[], policy_version="test")
    assert len(first.snapshot_hash) == len(first.chain_hash) == 64
    first_path = store.append(first)
    original_bytes = first_path.read_bytes()
    second = ValidationSnapshot(
        trip_id=first.trip_id,
        timestamp=first.timestamp + timedelta(seconds=1),
        policy_version="test",
        input_data=first.input_data,
        results=[],
        previous_hash=first.chain_hash,
    )
    store.append(second)

    reopened = ValidationSnapshotStore(tmp_path)
    assert reopened.load_snapshot(first_path) == first
    assert reopened.load_trip_snapshots(first.trip_id) == [first, second]
    assert reopened.last_chain_hash(first.trip_id) == second.chain_hash
    assert first_path.read_bytes() == original_bytes
