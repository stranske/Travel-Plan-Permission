"""Tests for receipt processing and reimbursement rules."""

from datetime import date
from decimal import Decimal

import pytest

from travel_plan_permission.models import ExpenseCategory, ExpenseItem, ExpenseReport
from travel_plan_permission.receipts import (
    MAX_RECEIPT_SIZE_BYTES,
    Receipt,
    ReceiptProcessor,
)


def _build_receipt(**overrides: object) -> Receipt:
    base_kwargs = {
        "total": Decimal("25.00"),
        "date": date(2025, 1, 5),
        "vendor": "Coffee Shop",
        "file_reference": "receipt.pdf",
        "file_size_bytes": 1024,
    }
    base_kwargs.update(overrides)
    return Receipt.model_validate(base_kwargs)


class TestReceiptValidation:
    def test_allowed_file_types(self) -> None:
        """Receipt accepts configured file extensions."""

        _build_receipt(file_reference="notes.png")
        _build_receipt(file_reference="scan.JPEG")
        _build_receipt(file_reference="image.HEIC")

        with pytest.raises(ValueError):
            _build_receipt(file_reference="document.txt")

    def test_file_size_limit_enforced(self) -> None:
        """Reject receipts over the 10MB size limit."""

        with pytest.raises(ValueError):
            _build_receipt(file_size_bytes=MAX_RECEIPT_SIZE_BYTES + 1)

    def test_manual_entry_marks_flag(self) -> None:
        """Manual entry helper sets the manual flag without OCR."""

        manual = Receipt.from_manual_entry(
            total=Decimal("18.00"),
            date=date(2025, 2, 1),
            vendor="Bakery",
            file_reference="bakery.png",
            file_size_bytes=2048,
            paid_by_third_party=False,
        )

        assert manual.manual_entry is True


class TestThirdPartyFlagging:
    def test_third_party_requires_explanation(self) -> None:
        """Expenses paid by a third party must include an explanation."""

        receipt = _build_receipt(paid_by_third_party=True)
        with pytest.raises(ValueError):
            ExpenseItem(
                category=ExpenseCategory.MEALS,
                description="Team lunch",
                amount=Decimal("45.00"),
                expense_date=date(2025, 1, 5),
                receipt_references=[receipt],
            )

    def test_reimbursable_total_excludes_third_party(self) -> None:
        """Report totals exclude third-party paid receipts."""

        sponsored_receipt = _build_receipt(
            paid_by_third_party=True, file_reference="sponsor.pdf"
        )
        sponsored_expense = ExpenseItem(
            category=ExpenseCategory.CONFERENCE_FEES,
            description="Conference pass",
            amount=Decimal("500.00"),
            expense_date=date(2025, 3, 10),
            receipt_references=[sponsored_receipt],
            third_party_paid_explanation="Provided by host organization",
        )
        reimbursable_expense = ExpenseItem(
            category=ExpenseCategory.MEALS,
            description="Team dinner",
            amount=Decimal("120.00"),
            expense_date=date(2025, 3, 11),
        )

        report = ExpenseReport(
            report_id="EXP-004",
            trip_id="TRIP-010",
            traveler_name="Alex Smith",
            expenses=[sponsored_expense, reimbursable_expense],
        )

        assert sponsored_expense.reimbursable_amount() == Decimal("0")
        assert report.total_amount() == Decimal("120.00")


class TestReceiptExtraction:
    def test_extract_from_text(self) -> None:
        """OCR extraction should parse totals, dates, and vendor."""

        text = "\n".join(
            [
                "Coffee Shop",
                "123 Main St",
                "Total: $12.50",
                "2025-01-05",
            ]
        )

        result = ReceiptProcessor.extract_from_text(text)

        assert result.total == Decimal("12.50")
        assert result.date == date(2025, 1, 5)
        assert result.vendor == "Coffee Shop"

    def test_extract_prefers_amount_due_over_subtotal(self) -> None:
        """Total parsing should prioritize the amount due figure."""

        text = "\n".join(
            [
                "Market Grocery",
                "Subtotal $8.00",
                "Tax 0.80",
                "Amount Due: 8.80",
                "12/30/2025",
            ]
        )

        result = ReceiptProcessor.extract_from_text(text)

        assert result.total == Decimal("8.80")
        assert result.date == date(2025, 12, 30)
        assert result.vendor == "Market Grocery"

    def test_extract_falls_back_to_largest_amount(self) -> None:
        """If keywords are missing, use the largest currency-looking value."""

        text = "\n".join(
            [
                "Cafe Latte",
                "Latte 3.50",
                "Muffin 2.75",
                "Tip 1.50",
                "7.75",
                "01/07/2025",
            ]
        )

        result = ReceiptProcessor.extract_from_text(text)

        assert result.total == Decimal("7.75")
        assert result.date == date(2025, 1, 7)
        assert result.vendor == "Cafe Latte"
