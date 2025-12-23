"""Receipt parsing and validation utilities."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date as dt_date
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

ALLOWED_RECEIPT_TYPES = {".pdf", ".png", ".jpeg", ".jpg", ".heic"}
MAX_RECEIPT_SIZE_BYTES = 10 * 1024 * 1024


class Receipt(BaseModel):
    """Metadata for an uploaded receipt."""

    total: Decimal = Field(..., ge=0, description="Total amount shown on the receipt")
    date: dt_date = Field(..., description="Transaction date on the receipt")
    vendor: str = Field(..., description="Merchant associated with the receipt")
    file_reference: str = Field(
        ..., description="Storage reference for the receipt file"
    )
    file_size_bytes: int = Field(
        ..., ge=0, description="Size of the uploaded receipt in bytes"
    )
    paid_by_third_party: bool = Field(
        default=False, description="Whether a third party paid the receipt"
    )
    manual_entry: bool = Field(
        default=False,
        description="True when the receipt details were manually entered instead of OCR",
    )

    @field_validator("file_reference")
    @classmethod
    def _validate_file_reference(cls, value: str) -> str:
        ext = Path(value).suffix.lower()
        normalized_ext = ".jpeg" if ext == ".jpg" else ext
        if normalized_ext not in ALLOWED_RECEIPT_TYPES:
            allowed = ", ".join(sorted(ALLOWED_RECEIPT_TYPES))
            raise ValueError(
                f"Unsupported receipt type '{ext}'. Allowed types: {allowed}"
            )
        return value

    @field_validator("file_size_bytes")
    @classmethod
    def _validate_file_size(cls, value: int) -> int:
        if value > MAX_RECEIPT_SIZE_BYTES:
            raise ValueError("Receipt file exceeds 10MB limit")
        return value

    @classmethod
    def from_manual_entry(
        cls,
        *,
        total: Decimal,
        date: dt_date,
        vendor: str,
        file_reference: str,
        file_size_bytes: int,
        paid_by_third_party: bool = False,
    ) -> Receipt:
        """Create a receipt using manually entered values."""

        return cls(
            total=total,
            date=date,
            vendor=vendor,
            file_reference=file_reference,
            file_size_bytes=file_size_bytes,
            paid_by_third_party=paid_by_third_party,
            manual_entry=True,
        )


class ReceiptExtractionResult(BaseModel):
    """Result of extracting fields from a receipt using OCR."""

    text: str = Field(..., description="Raw OCR text output")
    total: Decimal | None = Field(
        default=None, description="Parsed total amount from the receipt text"
    )
    date: dt_date | None = Field(
        default=None, description="Parsed transaction date from the receipt text"
    )
    vendor: str | None = Field(
        default=None, description="Parsed vendor from the receipt text"
    )


class ReceiptProcessor:
    """Minimal OCR-backed processing for receipts."""

    TOTAL_PATTERN = re.compile(
        r"(?:total|amount due)[:\s\$]*([0-9]+(?:[.,][0-9]{2})?)", re.IGNORECASE
    )
    DATE_PATTERN = re.compile(
        r"(\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", re.IGNORECASE
    )

    @staticmethod
    def extract_from_text(text: str) -> ReceiptExtractionResult:
        """Extract receipt details from OCR text output."""

        total = ReceiptProcessor._parse_total(text)
        parsed_date = ReceiptProcessor._parse_date(text)
        vendor = ReceiptProcessor._parse_vendor(text)
        return ReceiptExtractionResult(
            text=text, total=total, date=parsed_date, vendor=vendor
        )

    @staticmethod
    def extract_from_image(image_path: str) -> ReceiptExtractionResult:
        """Perform OCR on an image using pytesseract when available."""

        try:
            import pytesseract  # type: ignore[import-not-found]
            from PIL import Image  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ImportError(
                "pytesseract and Pillow are required for image extraction; install them to enable OCR."
            ) from exc

        text = pytesseract.image_to_string(Image.open(image_path))
        return ReceiptProcessor.extract_from_text(text)

    @staticmethod
    def _parse_total(text: str) -> Decimal | None:
        match = ReceiptProcessor.TOTAL_PATTERN.search(text)
        if not match:
            return None
        try:
            value = match.group(1).replace(",", "")
            return Decimal(value)
        except (InvalidOperation, IndexError):
            return None

    @staticmethod
    def _parse_date(text: str) -> dt_date | None:
        match = ReceiptProcessor.DATE_PATTERN.search(text)
        if not match:
            return None
        raw_date = match.group(1)
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d-%m-%Y", "%d-%m-%y"):
            try:
                if fmt == "%Y-%m-%d":
                    return dt_date.fromisoformat(raw_date)
                return datetime.strptime(raw_date, fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def _parse_vendor(text: str) -> str | None:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return None
        header = lines[0]
        if header.lower().startswith("receipt"):
            return lines[1] if len(lines) > 1 else None
        return header


def summarize_receipts(receipts: Iterable[Receipt]) -> dict[str, int]:
    """Return counts of receipts grouped by file type."""

    summary: dict[str, int] = {}
    for receipt in receipts:
        ext = Path(receipt.file_reference).suffix.lower() or "unknown"
        summary[ext] = summary.get(ext, 0) + 1
    return summary
