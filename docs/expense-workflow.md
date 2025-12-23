# Expense receipt workflow

## Supported uploads

- Allowed file types: PDF, JPEG/JPG, PNG, and HEIC.
- Maximum file size: 10MB per receipt.
- Each expense item can reference multiple receipts to support multi-page uploads or split payments.

## OCR and manual entry

- Basic OCR extraction uses `pytesseract` when available to pull vendor, total, and transaction date from uploaded images.
- When OCR is unavailable or fails, approvers can rely on manual entry for all receipt fields (vendor, total, date, file reference, third-party flag).
- OCR results are stored alongside the receipt metadata so manual corrections can override them if needed.

## Third-party payments

- Receipts marked as `paid_by_third_party` require an explanation on the associated expense item.
- Expenses covered by third parties are flagged and excluded from the reimbursement total to avoid double payment.

## Data model highlights

- `Receipt` captures vendor, total, date, storage reference, file size, and a third-party flag.
- `ExpenseItem` includes a `receipt_references` list, enabling multiple receipts per line item and third-party tracking.
- `ExpenseReport.total_amount()` now returns the reimbursable total, omitting third-party covered expenses.
