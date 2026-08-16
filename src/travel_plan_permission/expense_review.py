"""Expense-review state construction, isolated from HTTP route wiring."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import ValidationError

from .approval import ApprovalEngine
from .models import ApprovalStatus, ExpenseCategory, ExpenseItem, ExpenseReport
from .receipts import Receipt, ReceiptExtractionResult, ReceiptProcessor


def build_expense_review_state[StoreT](
    draft_id: str,
    answers: dict[str, object],
    *,
    proposal_store: StoreT | None,
    required_fields: tuple[str, ...],
    linkage_validator: Callable[[StoreT | None, dict[str, object]], Any],
    artifact_builder: Callable[..., dict[str, Any]],
    state_factory: Callable[..., object],
) -> object:
    """Build expense validation, report, and export state without route coupling."""

    missing_fields = [field_name for field_name in required_fields if not answers.get(field_name)]
    validation_errors: list[str] = []
    review_warnings: list[str] = []
    receipt_state = "missing"
    receipt_extraction: ReceiptExtractionResult | None = None
    expense_report: ExpenseReport | None = None
    artifacts: dict[str, object] = {}
    linkage_validation = linkage_validator(proposal_store, {})

    ocr_text = answers.get("receipt_ocr_text")
    if isinstance(ocr_text, str) and ocr_text.strip():
        receipt_extraction = ReceiptProcessor.extract_from_text(ocr_text)

    if not missing_fields:
        linkage_validation = linkage_validator(proposal_store, answers)
        validation_errors.extend(linkage_validation.errors)
        try:
            category = ExpenseCategory(str(answers["expense_category"]))
            expense_amount = Decimal(str(answers["expense_amount"]))
            expense_date = date.fromisoformat(str(answers["expense_date"]))
            receipt_reference = answers.get("receipt_file_reference")
            receipt: Receipt | None = None
            if receipt_reference:
                if not all(
                    answers.get(name)
                    for name in (
                        "receipt_file_size_bytes",
                        "receipt_total",
                        "receipt_date",
                        "receipt_vendor",
                    )
                ):
                    validation_errors.append(
                        "Receipt uploads require file size, total, date, and vendor details."
                    )
                    receipt_state = "incomplete"
                else:
                    receipt = Receipt.from_manual_entry(
                        total=Decimal(str(answers["receipt_total"])),
                        date=date.fromisoformat(str(answers["receipt_date"])),
                        vendor=str(answers["receipt_vendor"]),
                        file_reference=str(receipt_reference),
                        file_size_bytes=int(str(answers["receipt_file_size_bytes"])),
                        paid_by_third_party=bool(answers.get("receipt_paid_by_third_party")),
                    )
                    receipt_state = "attached"
                    if receipt_extraction is not None:
                        mismatches = [
                            name
                            for name, extracted, actual in (
                                ("vendor", receipt_extraction.vendor, receipt.vendor),
                                ("total", receipt_extraction.total, receipt.total),
                                ("date", receipt_extraction.date, receipt.date),
                            )
                            if extracted is not None and extracted != actual
                        ]
                        if mismatches:
                            review_warnings.append(
                                "Manual receipt entry overrides OCR values for "
                                + ", ".join(mismatches)
                                + "."
                            )
            else:
                review_warnings.append(
                    "Receipt missing: reviewers should hold reimbursement until the traveler uploads support."
                )

            if not linkage_validation.blocks_export:
                expense = ExpenseItem(
                    category=category,
                    description=str(answers["expense_description"]),
                    vendor=str(answers.get("expense_vendor") or "") or None,
                    amount=expense_amount,
                    expense_date=expense_date,
                    receipt_attached=receipt is not None,
                    receipt_url=str(receipt_reference) if receipt_reference else None,
                    receipt_references=[receipt] if receipt is not None else [],
                    third_party_paid_explanation=(
                        str(answers["third_party_paid_explanation"])
                        if answers.get("third_party_paid_explanation")
                        else None
                    ),
                )
                expense_report = ApprovalEngine.from_file().evaluate_report(
                    ExpenseReport(
                        report_id=f"EXP-{draft_id.upper()}",
                        trip_id=str(answers["trip_id"]),
                        traveler_name=str(answers["traveler_name"]),
                        cost_center=str(answers.get("cost_center") or "") or None,
                        expenses=[expense],
                    )
                )
                if expense_report.approval_status == ApprovalStatus.FLAGGED:
                    review_warnings.append(
                        "Policy warning: manager or accounting review is required before reimbursement."
                    )
                artifacts = artifact_builder(draft_id=draft_id, expense_report=expense_report)
        except ValidationError as exc:
            validation_errors.extend(
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors()
            )
        except FileNotFoundError:
            validation_errors.append(
                "Approval rules configuration is unavailable; expense policy review cannot be completed."
            )
        except InvalidOperation:
            validation_errors.append("One or more currency amounts are not valid decimal values.")
        except ValueError as exc:
            validation_errors.append(str(exc))

    return state_factory(
        draft_id=draft_id,
        answers=answers,
        missing_fields=missing_fields,
        validation_errors=validation_errors,
        receipt_state=receipt_state,
        receipt_extraction=receipt_extraction,
        expense_report=expense_report,
        review_warnings=review_warnings,
        artifacts=artifacts,
    )
