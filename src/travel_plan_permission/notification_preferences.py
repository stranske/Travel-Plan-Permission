"""Notification preference models and storage helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import BaseModel, Field


class NotificationPreferences(BaseModel):
    """Stored notification preferences for a user."""

    trip_status_updates: bool = Field(
        default=True, description="Whether to send trip status updates"
    )
    expense_reminders: bool = Field(
        default=True, description="Whether to send post-trip expense reminders"
    )
    policy_digests: bool = Field(default=True, description="Whether to send policy update digests")
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp of the latest preference update",
    )


class NotificationPreferencesUpdate(BaseModel):
    """Partial update payload for notification preferences."""

    trip_status_updates: bool | None = Field(
        default=None, description="Updated trip status preference"
    )
    expense_reminders: bool | None = Field(
        default=None, description="Updated expense reminder preference"
    )
    policy_digests: bool | None = Field(
        default=None, description="Updated policy digest preference"
    )

    def apply_to(self, current: NotificationPreferences) -> NotificationPreferences:
        """Return a new NotificationPreferences with updates applied."""

        data = current.model_dump()
        data.update(self.model_dump(exclude_none=True))
        data["updated_at"] = datetime.now(UTC)
        return NotificationPreferences(**data)


@dataclass
class NotificationPreferenceStore:
    """In-memory store for notification preferences keyed by user id."""

    preferences: dict[str, NotificationPreferences] = field(default_factory=dict)

    def get_preferences(self, user_id: str) -> NotificationPreferences:
        """Return stored preferences for a user or defaults."""

        return self.preferences.get(user_id, NotificationPreferences())

    def save_preferences(
        self, user_id: str, preferences: NotificationPreferences
    ) -> NotificationPreferences:
        """Persist full notification preferences for a user."""

        self.preferences[user_id] = preferences
        return preferences

    def update_preferences(
        self, user_id: str, update: NotificationPreferencesUpdate
    ) -> NotificationPreferences:
        """Persist a partial update to a user's preferences."""

        current = self.get_preferences(user_id)
        updated = update.apply_to(current)
        self.preferences[user_id] = updated
        return updated
