"""Tests for provider registry loading and lookup."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

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

    assert registry.version == "2026.09"
    assert registry.approver == "Travel Operations Manager"
    assert registry.change_log, "Change log should capture provider list updates"


@pytest.mark.parametrize("path", ["config/providers.yaml", None])
def test_shipped_registry_has_active_providers_today(path: str | None) -> None:
    config_path = Path(__file__).resolve().parents[2] / path if path else None
    registry = ProviderRegistry.from_file(config_path)

    assert registry.active_providers(reference_date=date.today())
    assert registry.active_providers()
    registry.assert_has_active_providers()
    assert registry.is_approved("Blue Skies Airlines", ProviderType.AIRLINE, "london")


def test_shipped_provider_config_matches_packaged_copy() -> None:
    root = Path(__file__).resolve().parents[2]
    assert (root / "config/providers.yaml").read_bytes() == (
        root / "src/travel_plan_permission/config/providers.yaml"
    ).read_bytes()


@pytest.mark.parametrize("reference_date", [date(2020, 1, 1), date(2028, 1, 1)])
def test_registry_health_reports_inactive_contracts(reference_date: date) -> None:
    registry = ProviderRegistry.from_file()

    with pytest.raises(ValueError) as error:
        registry.assert_has_active_providers(reference_date)

    assert registry.version in str(error.value)
    assert str(registry.updated_at) in str(error.value)
    assert "4 providers checked, 0 active" in str(error.value)


def test_registry_health_accepts_historical_active_contracts() -> None:
    ProviderRegistry.from_file().assert_has_active_providers(date(2024, 6, 1))
