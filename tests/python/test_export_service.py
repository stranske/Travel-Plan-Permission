"""Tests for accounting export service.

Run opt-in performance coverage with:
    pytest -m perf tests/python/test_export_service.py
"""

from __future__ import annotations

import csv
import os
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from io import BytesIO, StringIO
from pathlib import Path
from time import perf_counter
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse

import pytest
from openpyxl import load_workbook

from travel_plan_permission import ExportService
from travel_plan_permission.models import (
    ApprovalStatus,
    ExpenseCategory,
    ExpenseItem,
    ExpenseReport,
)


def _sample_report() -> ExpenseReport:
    return ExpenseReport(
        report_id="EXP-100",
        trip_id="TRIP-100",
        traveler_name="Terry Traveler",
        cost_center="ENG",
        approval_status=ApprovalStatus.PENDING,
        expenses=[
            ExpenseItem(
                category=ExpenseCategory.MEALS,
                description="Client dinner",
                vendor="Bistro Cafe",
                amount=Decimal("125.50"),
                expense_date=date(2025, 1, 12),
                receipt_attached=True,
                receipt_url="/receipts/abc123",
            )
        ],
    )


def _typical_batch_reports() -> list[ExpenseReport]:
    reports: list[ExpenseReport] = []
    for report_idx in range(50):
        expenses = [
            ExpenseItem(
                category=ExpenseCategory.GROUND_TRANSPORT,
                description=f"Taxi ride {expense_idx}",
                vendor="City Cabs",
                amount=Decimal("25.00") + Decimal(expense_idx),
                expense_date=date(2025, 3, 15 + expense_idx),
                receipt_attached=True,
                receipt_url=f"/receipts/{report_idx}-{expense_idx}",
            )
            for expense_idx in range(4)
        ]
        reports.append(
            ExpenseReport(
                report_id=f"EXP-{report_idx:03}",
                trip_id=f"TRIP-{report_idx:03}",
                traveler_name=f"Traveler {report_idx}",
                cost_center="OPS",
                approval_status=ApprovalStatus.AUTO_APPROVED,
                expenses=expenses,
            )
        )
    return reports


@pytest.mark.parametrize(
    ("text", "csv_text"),
    [
        ("=1+1", "'=1+1"),
        ("+1+1", "'+1+1"),
        ("-1+1", "'-1+1"),
        ("@SUM(1,1)", "'@SUM(1,1)"),
        ("  =1+1", "'  =1+1"),
        ("\t=1+1", "'\t=1+1"),
        ("\r=1+1", "'\r=1+1"),
        ("\n=1+1", "'\n=1+1"),
        (" \t\r\n+1+1", "' \t\r\n+1+1"),
        ("\tplain text", "'\tplain text"),
        (" leading space", "' leading space"),
        ("\u00a0=1+1", "'\u00a0=1+1"),
        ("＝1+1", "'＝1+1"),
        ("＋1+1", "'＋1+1"),
        ("－1+1", "'－1+1"),
        ("＠SUM(1,1)", "'＠SUM(1,1)"),
        ('=1+1,";=2+2', "'=1+1,\";=2+2"),
        ('Acme, "West"\n=1+1', 'Acme, "West"\n=1+1'),
        ("#N/A", "#N/A"),
        ("Ordinary text", "Ordinary text"),
        ("http://[broken", "http://[broken"),
        ("https://:443/receipt", "https://:443/receipt"),
        ("https://user@/receipt", "https://user@/receipt"),
        ("http://receipts.example.test/one", "http://receipts.example.test/one"),
        ("https://receipts.example.test/one?x=1&y=2", "https://receipts.example.test/one?x=1&y=2"),
    ],
)
def test_export_preserves_literal_user_text(text: str, csv_text: str) -> None:
    """Inspect saved artifacts without evaluating formulas or following links."""
    report = _sample_report()
    report.expenses[0].vendor = text
    report.cost_center = text
    from travel_plan_permission.receipt_delivery import ReceiptDelivery

    # Isolate serialization from delivery validation, which has its own contract tests.
    delivery = Mock(spec=ReceiptDelivery)
    delivery.resolve.return_value = text
    service = ExportService(receipt_delivery=delivery)
    now = datetime(2025, 1, 20, 10, 0, tzinfo=UTC)

    _, workbook_content = service.to_excel([report], batch_id="literal", now=now)
    sheet = load_workbook(BytesIO(workbook_content), data_only=False).active
    for address in ("B2", "E2", "F2"):
        assert sheet[address].value == text
        assert sheet[address].data_type == "s"
    assert sheet["C2"].data_type == "n"
    assert sheet["C2"].value == 125.5
    if text.startswith(("http://receipts.", "https://receipts.")):
        assert sheet["F2"].hyperlink.target == text
    else:
        assert sheet["F2"].hyperlink is None

    _, csv_content = service.to_csv([report], batch_id="literal", now=now)
    rows = list(csv.DictReader(StringIO(csv_content, newline="")))
    assert len(rows) == 1
    assert set(rows[0]) == set(service.schema)
    for field in ("vendor", "cost_center", "receipt_link"):
        assert rows[0][field] == csv_text
    assert rows[0]["amount"] == "125.50"
    assert report.expenses[0].vendor == text
    assert report.cost_center == text


def test_export_literal_text_without_lxml() -> None:
    """Exercise the actual fallback writer even on developer machines with lxml."""
    test_file = Path(__file__).resolve()
    code = (
        "import openpyxl, runpy\n"
        "assert not openpyxl.LXML\n"
        f"test = runpy.run_path({str(test_file)!r})['test_export_preserves_literal_user_text']\n"
        "for text in ('\\r=1+1', ' \\t\\r\\n+1+1'):\n"
        '    test(text, "\'" + text)\n'
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "OPENPYXL_LXML": "False"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


class TestExportService:
    """Accounting export behavior."""

    def test_csv_header_and_column_order(self, receipt_hosted_delivery) -> None:
        """CSV export should be UTF-8 with expected header order."""
        service = ExportService(receipt_delivery=receipt_hosted_delivery)
        now = datetime(2025, 1, 20, 10, 0, tzinfo=UTC)
        filename, content = service.to_csv([_sample_report()], batch_id="batch-1", now=now)

        assert filename == "expense_export_2025-01-20_batch-1.csv"
        header = content.splitlines()[0]
        assert header == "date,vendor,amount,category,cost_center,receipt_link"
        # Ensure UTF-8 encodes without errors
        content.encode("utf-8")

    def test_receipt_link_expiry_is_7_days(self, receipt_hosted_delivery) -> None:
        """Receipt links should expire in exactly 7 days."""
        service = ExportService(receipt_delivery=receipt_hosted_delivery)
        now = datetime(2025, 2, 1, 8, 30, tzinfo=UTC)
        _, content = service.to_csv([_sample_report()], batch_id="batch-2", now=now)
        row = content.splitlines()[1].split(",")
        receipt_link = row[-1]

        parsed = urlparse(receipt_link)
        params = parse_qs(parsed.query)
        expires_at = params["expires"][0]
        expires_dt = datetime.fromtimestamp(int(expires_at), UTC)

        assert expires_dt - now == timedelta(days=7)
        assert parsed.scheme in {"http", "https"}

    def test_excel_currency_and_hyperlink(self, receipt_hosted_delivery) -> None:
        """Excel export should format amount as currency and set clickable hyperlinks."""
        service = ExportService(receipt_delivery=receipt_hosted_delivery)
        now = datetime(2025, 3, 5, 12, 0, tzinfo=UTC)
        filename, content = service.to_excel([_sample_report()], batch_id="batch-3", now=now)

        assert filename == "expense_export_2025-03-05_batch-3.xlsx"
        workbook = load_workbook(BytesIO(content))
        sheet = workbook.active

        assert [cell.value for cell in sheet[1]] == service.schema
        amount_cell = sheet.cell(row=2, column=3)
        assert amount_cell.number_format == "$#,##0.00"
        receipt_cell = sheet.cell(row=2, column=6)
        assert receipt_cell.hyperlink is not None
        assert receipt_cell.hyperlink.target.startswith("https://")

    def test_batch_size_limit(self, receipt_hosted_delivery) -> None:
        """Batch export should reject more than 100 reports."""
        service = ExportService(receipt_delivery=receipt_hosted_delivery)
        reports = [_sample_report() for _ in range(101)]

        with pytest.raises(ValueError):
            service.to_csv(reports, batch_id="too-many")

    def test_schema_column_order_matches_acceptance(self) -> None:
        """Schema column order must match documented schema exactly."""
        assert ExportService.schema == [
            "date",
            "vendor",
            "amount",
            "category",
            "cost_center",
            "receipt_link",
        ]

    def test_typical_batch_exports_have_expected_outputs(self, receipt_hosted_delivery) -> None:
        """Typical batch coverage should stay in the default unit lane."""
        service = ExportService(receipt_delivery=receipt_hosted_delivery)
        now = datetime(2025, 4, 1, 9, 0, tzinfo=UTC)
        reports = _typical_batch_reports()

        csv_filename, csv_content = service.to_csv(reports, batch_id="typical-csv", now=now)
        excel_filename, excel_content = service.to_excel(reports, batch_id="typical-xlsx", now=now)

        assert csv_filename == "expense_export_2025-04-01_typical-csv.csv"
        assert csv_content.splitlines()[0] == ",".join(service.schema)
        assert len(csv_content.splitlines()) == 201
        assert excel_filename == "expense_export_2025-04-01_typical-xlsx.xlsx"
        workbook = load_workbook(BytesIO(excel_content))
        sheet = workbook.active
        assert [cell.value for cell in sheet[1]] == service.schema
        assert sheet.max_row == 201

    @pytest.mark.perf
    def test_exports_complete_within_five_seconds_for_typical_batch(
        self, receipt_hosted_delivery
    ) -> None:
        """CSV and Excel exports should finish quickly for typical batch sizes."""
        service = ExportService(receipt_delivery=receipt_hosted_delivery)
        now = datetime(2025, 4, 1, 9, 0, tzinfo=UTC)
        reports = _typical_batch_reports()

        start = perf_counter()
        service.to_csv(reports, batch_id="perf-csv", now=now)
        service.to_excel(reports, batch_id="perf-xlsx", now=now)
        elapsed = perf_counter() - start

        assert elapsed < 5, f"Exports took too long: {elapsed:.2f}s"


def test_receipt_link_requires_real_delivery_mode(tmp_path, receipt_hosted_delivery) -> None:
    import csv
    from dataclasses import replace
    from io import StringIO
    from pathlib import Path
    from urllib.parse import unquote, urlsplit

    from travel_plan_permission.receipt_delivery import ReceiptDelivery

    report = _sample_report()
    report.expenses[0].receipt_url = "receipt.pdf"
    receipt = tmp_path / "receipt.pdf"
    receipt.write_bytes(b"source receipt evidence")
    now = datetime(2025, 2, 1, 8, 30, tzinfo=UTC)

    def link(service):
        _, content = service.to_csv([report], batch_id="delivery", now=now)
        assert "receipts.example.com" not in content
        return next(csv.DictReader(StringIO(content)))["receipt_link"]

    with pytest.raises(ValueError, match="not configured"):
        link(ExportService())
    local = ExportService(receipt_delivery=ReceiptDelivery("local-reference", root=tmp_path))
    reference = link(local)
    assert urlsplit(reference).query == ""
    assert Path(unquote(urlsplit(reference).path)).read_bytes() == receipt.read_bytes()
    for missing in ("absent.pdf", "../outside.pdf", str(receipt)):
        report.expenses[0].receipt_url = missing
        with pytest.raises(ValueError, match="cannot be resolved"):
            link(local)
    report.expenses[0].receipt_url = "receipt.pdf"
    receipt.unlink()
    outside = tmp_path.parent / (tmp_path.name + "-outside.pdf")
    outside.write_bytes(b"outside root")
    receipt.symlink_to(outside)
    with pytest.raises(ValueError, match="cannot be resolved"):
        link(local)

    receipt.unlink()
    outside.unlink()

    hosted = ExportService(receipt_delivery=receipt_hosted_delivery)
    signed = link(hosted)
    expiry = now + timedelta(days=7)
    verify = receipt_hosted_delivery.verifier
    assert verify(signed, "receipt.pdf", expiry, now)
    assert not verify(signed.replace("receipt.pdf", "other.pdf"), "receipt.pdf", expiry, now)
    assert not verify(signed, "receipt.pdf", expiry, expiry)
    assert not verify(signed.replace("expires=", "expires=9"), "receipt.pdf", expiry, now)
    assert not verify(signed.replace("signature=", "signature=bad"), "receipt.pdf", expiry, now)
    for invalid in (
        "https://receipts.example.com/receipt?expires=123",
        "https://receipts.finance.internal/receipt?expires=123",
        "https://other.internal/receipt?signature=123",
        "https://:443/receipt",
        "file:///receipt",
        "not-a-url",
    ):
        delivery = replace(
            receipt_hosted_delivery, signer=lambda _ref, _expiry, result=invalid: result
        )
        with pytest.raises(ValueError, match="Receipt delivery failed"):
            link(ExportService(receipt_delivery=delivery))
    with pytest.raises(ValueError, match="origin, signer, and verifier"):
        link(ExportService(receipt_delivery=ReceiptDelivery("hosted-signed")))
    # Receipt-free reports still export without requiring hosted infrastructure.
    report.expenses[0].receipt_url = None
    assert link(ExportService()) == ""


@pytest.mark.parametrize("port", ["0", "-1", "65536", "notaport", "443", "8443", "65535"])
def test_receipt_delivery_validates_explicit_ports(receipt_hosted_delivery, port):
    from dataclasses import replace

    now = datetime(2025, 1, 20, 10, 0, tzinfo=UTC)
    origin = receipt_hosted_delivery.origin
    with_port = f"{origin}:{port}"
    signer = receipt_hosted_delivery.signer
    configured = replace(
        receipt_hosted_delivery,
        origin=with_port,
        signer=lambda ref, expiry: signer(ref, expiry).replace(origin, with_port, 1),
    )
    if port in {"443", "8443", "65535"}:
        assert configured.resolve("receipt.pdf", now).startswith(with_port + "/")
    else:
        with pytest.raises(ValueError, match="real HTTPS origin"):
            configured.resolve("receipt.pdf", now)
        # Validate the signer URL independently of the configured origin.
        with pytest.raises(ValueError, match="Receipt delivery failed"):
            replace(configured, origin=origin).resolve("receipt.pdf", now)


@pytest.mark.parametrize(
    "tampering",
    [
        "&receipt=receipt.pdf",
        "&expires=999",
        "&signature=valid",
        "&receipt=",
        "&expires=",
        "&signature=",
        "&unexpected=value",
        "&unexpected=",
    ],
)
def test_receipt_verifier_rejects_query_tampering(receipt_hosted_delivery, tampering):
    now = datetime(2025, 1, 20, 10, 0, tzinfo=UTC)
    expiry = now + timedelta(days=7)
    signed = receipt_hosted_delivery.resolve("receipt.pdf", now)
    verify = receipt_hosted_delivery.verifier
    assert verify(signed, "receipt.pdf", expiry, now)
    assert not verify(signed + tampering, "receipt.pdf", expiry, now)
