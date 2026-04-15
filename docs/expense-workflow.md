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

## Portal review flow

- The browser-facing expense portal lives at `/portal/expenses/new` and links every draft to an approved request identifier before export.
- Reviewers can see three explicit states in one screen: receipt missing/incomplete vs attached, policy warnings from the approval engine, and the current reimbursement/accounting disposition.
- Accounting handoff artifacts are generated through `ExportService.to_csv()` and `ExportService.to_excel()` so the portal reuses the existing export layer rather than producing ad hoc files.
- OCR text is optional and advisory: extracted vendor/total/date are surfaced next to the manually entered receipt values so reviewers can spot mismatches before reimbursement.

## Current boundary

- This stage stops at export-ready accounting handoff artifacts and status tracking inside the portal UI.
- Direct ERP or reimbursement-system writes remain out of scope until a later integration pass.
