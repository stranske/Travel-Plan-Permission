"""Tests for provider registry loading and lookup."""

from __future__ import annotations

from datetime import date

from travel_plan_permission.providers import ProviderRegistry, ProviderType


def test_lookup_filters_by_destination_and_validity() -> None:
    registry = ProviderRegistry.from_file("config/providers.yaml")

    london_airlines = registry.lookup(
        ProviderType.AIRLINE, "London, UK", reference_date=date(2024, 6, 1)
    )
    assert [provider.name for provider in london_airlines] == ["Blue Skies Airlines"]

    expired_hotels = registry.lookup(
        ProviderType.HOTEL, "Seattle, WA", reference_date=date(2024, 3, 1)
    )
    assert expired_hotels == []


def test_registry_metadata_requires_approver_and_version() -> None:
    registry = ProviderRegistry.from_file("config/providers.yaml")

    assert registry.version == "2024.09"
    assert registry.approver == "Travel Operations Manager"
    assert registry.change_log, "Change log should capture provider list updates"
