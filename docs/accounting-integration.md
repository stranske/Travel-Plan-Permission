# Accounting Export Schema

The accounting export provides CSV and Excel outputs that finance teams can import directly into downstream systems.

The browser-facing expense portal at `/portal/expenses/new` now generates these same artifacts for draft reimbursement reports, so accounting handoff stays aligned with the repo’s shared export layer.

## Column schema and order

The exports always include a header row using the following columns in order:

1. `date` – ISO-8601 expense date (YYYY-MM-DD).
2. `vendor` – Merchant or vendor for the expense.
3. `amount` – Decimal amount with two digits of precision.
4. `category` – Expense category (matches `ExpenseCategory` enum).
5. `cost_center` – Cost center associated with the expense report.
6. `receipt_link` – Signed URL valid for 7 days.

## File naming

Exports follow the pattern:

```
expense_export_{date}_{batch_id}.{ext}
```

* `date` is the current UTC date (YYYY-MM-DD).
* `batch_id` is provided by the caller to correlate batches.
* `ext` is `csv` or `xlsx`.

## Receipt links

Receipt links are signed for 7 days and emitted as clickable hyperlinks in the Excel export. They are intended for short-lived sharing with accounting systems.

## Limits and performance

* Batch exports support up to **100** expense reports.
* CSV output is UTF-8 encoded with a header row.
* Excel amounts are formatted with currency number formatting for rapid review.
* The expense portal is export-only for now; direct accounting-system writes remain out of scope.
