"""Tests for validation snapshot capture and re-checking."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from travel_plan_permission.models import TripPlan
from travel_plan_permission.snapshots import (
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
    rule = DurationLimitRule(
        name="duration_limit", code="DUR-001", max_consecutive_days=max_days
    )
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
