"""Provider registry and lookup utilities for approved travel vendors."""

from __future__ import annotations

from datetime import date
from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProviderType(str, Enum):
    """Categories of supported travel providers."""

    AIRLINE = "airline"
    HOTEL = "hotel"
    GROUND_TRANSPORT = "ground_transport"


def provider_type_for_category(category: str) -> ProviderType | None:
    """Map an expense category string to a provider type when applicable."""

    normalized = category.lower()
    if normalized == "airfare":
        return ProviderType.AIRLINE
    if normalized == "lodging":
        return ProviderType.HOTEL
    if normalized == "ground_transport":
        return ProviderType.GROUND_TRANSPORT
    return None


class Provider(BaseModel):
    """An approved travel provider record."""

    name: str = Field(..., description="Display name of the provider")
    type: ProviderType = Field(..., description="Category of provider")
    contract_id: str = Field(..., description="Internal contract identifier")
    valid_from: date = Field(..., description="Contract start date")
    valid_to: date | None = Field(
        default=None, description="Contract end date; None when open-ended"
    )
    destinations: list[str] = Field(
        default_factory=list,
        description=(
            "Destination keywords (case-insensitive substring) where the provider applies; "
            "empty means globally applicable"
        ),
    )
    rate_notes: str | None = Field(
        default=None, description="Optional notes about negotiated rates"
    )

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _validate_dates(self) -> Provider:
        if self.valid_to and self.valid_to < self.valid_from:
            msg = "valid_to must be on or after valid_from"
            raise ValueError(msg)
        return self

    def is_active(self, reference_date: date | None = None) -> bool:
        """Return True when the provider contract is active for the reference date."""

        check_date = reference_date or date.today()
        if check_date < self.valid_from:
            return False
        if self.valid_to and check_date > self.valid_to:
            return False
        return True

    def matches_destination(self, destination: str) -> bool:
        """Return True when the provider applies to the requested destination."""

        if not self.destinations:
            return True
        destination_lower = destination.lower()
        return any(keyword.lower() in destination_lower for keyword in self.destinations)


class ProviderChange(BaseModel):
    """Audit entry for changes to the provider list."""

    version: str = Field(..., description="Version identifier for the change")
    change_date: date = Field(
        ..., alias="date", description="Date the change was approved"
    )
    description: str = Field(..., description="Summary of the change")
    approver: str = Field(..., description="Person or role who approved the change")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ProviderRegistry(BaseModel):
    """Registry of approved providers with lookup helpers."""

    version: str = Field(..., description="Version tag for the provider list")
    approver: str = Field(..., description="Designated approver for list updates")
    updated_at: date = Field(..., description="Last updated timestamp for the registry")
    change_log: list[ProviderChange] = Field(
        default_factory=list, description="Audit trail of provider list updates"
    )
    providers: list[Provider] = Field(
        default_factory=list, description="Collection of approved providers"
    )

    model_config = ConfigDict(extra="forbid")

    @classmethod
    def from_yaml(cls, content: str) -> ProviderRegistry:
        """Instantiate a registry from YAML content."""

        data = yaml.safe_load(content) or {}
        providers = data.get("providers")
        if not providers:
            raise ValueError("Provider configuration must include a 'providers' list")
        return cls.model_validate(data)

    @classmethod
    def from_file(cls, path: str | Path | None = None) -> ProviderRegistry:
        """Load provider configuration from a file, falling back to the default path."""

        target_path = cls._resolve_path(path)
        return cls.from_yaml(target_path.read_text(encoding="utf-8"))

    @staticmethod
    def _default_path() -> Path | None:
        for parent in Path(__file__).resolve().parents:
            candidate = parent / "config" / "providers.yaml"
            if candidate.exists():
                return candidate
        return None

    @classmethod
    def _resolve_path(cls, path: str | Path | None) -> Path:
        if path is None:
            default_path = cls._default_path()
            if default_path is None:
                raise FileNotFoundError("No providers.yaml file found")
            return default_path

        candidate = Path(path)
        if candidate.is_absolute() and candidate.exists():
            return candidate

        for parent in Path(__file__).resolve().parents:
            relative_candidate = parent / candidate
            if relative_candidate.exists():
                return relative_candidate
        return candidate

    def lookup(
        self,
        provider_type: ProviderType,
        destination: str,
        *,
        reference_date: date | None = None,
    ) -> list[Provider]:
        """Return approved providers for the type and destination."""

        return sorted(
            [
                provider
                for provider in self.providers
                if provider.type == provider_type
                and provider.is_active(reference_date)
                and provider.matches_destination(destination)
            ],
            key=lambda provider: provider.name.lower(),
        )

    def is_approved(
        self,
        provider_name: str,
        provider_type: ProviderType,
        destination: str,
        *,
        reference_date: date | None = None,
    ) -> bool:
        """Return True when the provider name is approved for the destination."""

        approved_names = {
            provider.name
            for provider in self.lookup(
                provider_type, destination, reference_date=reference_date
            )
        }
        return provider_name in approved_names

    def active_providers(
        self, *, reference_date: date | None = None
    ) -> list[Provider]:
        """Return all providers with an active contract for the given date."""

        return [
            provider
            for provider in self.providers
            if provider.is_active(reference_date=reference_date)
        ]
