from __future__ import annotations

from datetime import UTC, datetime

from travel_plan_permission.notification_preferences import (
    NotificationPreferenceStore,
    NotificationPreferences,
    NotificationPreferencesUpdate,
)


def test_notification_preferences_saved_per_user() -> None:
    store = NotificationPreferenceStore()
    fixed_time = datetime(2024, 1, 1, tzinfo=UTC)
    alice_preferences = NotificationPreferences(
        trip_status_updates=False,
        expense_reminders=True,
        policy_digests=False,
        updated_at=fixed_time,
    )
    bob_preferences = NotificationPreferences(
        trip_status_updates=True,
        expense_reminders=False,
        policy_digests=True,
        updated_at=fixed_time,
    )

    store.save_preferences("alice", alice_preferences)
    store.save_preferences("bob", bob_preferences)

    assert store.get_preferences("alice") == alice_preferences
    assert store.get_preferences("bob") == bob_preferences


def test_notification_preferences_update_merges_existing_values() -> None:
    store = NotificationPreferenceStore()
    fixed_time = datetime(2024, 1, 1, tzinfo=UTC)
    initial = NotificationPreferences(
        trip_status_updates=True,
        expense_reminders=False,
        policy_digests=True,
        updated_at=fixed_time,
    )
    store.save_preferences("alice", initial)

    update = NotificationPreferencesUpdate(expense_reminders=True)
    updated = store.update_preferences("alice", update)

    assert updated.trip_status_updates is True
    assert updated.expense_reminders is True
    assert updated.policy_digests is True
    assert updated.updated_at > fixed_time
