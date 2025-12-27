"""Test configuration for adding src to the import path."""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC_PATH = ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from travel_plan_permission import ExpenseCategory, Receipt, TripPlan


@pytest.fixture()
def trip_plan_factory() -> Callable[..., TripPlan]:
    def _factory(**overrides: object) -> TripPlan:
        data = {
            "trip_id": "TRIP-API-001",
            "traveler_name": "Alex Rivera",
            "destination": "New York, NY",
            "departure_date": date(2024, 9, 15),
            "return_date": date(2024, 9, 20),
            "purpose": "Client workshop",
            "estimated_cost": Decimal("1000.00"),
            "expense_breakdown": {
                ExpenseCategory.AIRFARE: Decimal("400.00"),
                ExpenseCategory.GROUND_TRANSPORT: Decimal("150.00"),
            },
        }
        data.update(overrides)
        return TripPlan(**data)

    return _factory


@pytest.fixture()
def base_trip_plan(trip_plan_factory: Callable[..., TripPlan]) -> TripPlan:
    return trip_plan_factory()


@pytest.fixture()
def receipt_factory() -> Callable[..., Receipt]:
    def _factory(**overrides: object) -> Receipt:
        data = {
            "total": Decimal("500.00"),
            "date": date(2024, 9, 16),
            "vendor": "Metro Cab",
            "file_reference": "receipt-001.pdf",
            "file_size_bytes": 1024,
        }
        data.update(overrides)
        return Receipt(**data)

    return _factory


@pytest.fixture()
def sample_receipts(receipt_factory: Callable[..., Receipt]) -> list[Receipt]:
    return [
        receipt_factory(),
        receipt_factory(
            total=Decimal("700.00"),
            date=date(2024, 9, 17),
            vendor="Hotel Central",
            file_reference="receipt-002.png",
            file_size_bytes=2048,
        ),
    ]
