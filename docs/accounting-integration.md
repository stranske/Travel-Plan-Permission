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
6. `receipt_link` – Validated local file reference or hosted signed URL, according to the configured delivery mode.

## File naming

Exports follow the pattern:

```
expense_export_{date}_{batch_id}.{ext}
```

* `date` is the current UTC date (YYYY-MM-DD).
* `batch_id` is provided by the caller to correlate batches.
* `ext` is `csv` or `xlsx`.

## Receipt links

No delivery mode is assumed. Reports without receipts can export without configuration;
a referenced receipt blocks export with a validation error until delivery is configured.
The portal uses the same configuration for preview, review, and artifact downloads.
Downloads regenerate references, so expired hosted URLs or old cached placeholder links
are never reused as newly validated delivery.

### Local reference mode (no hosting required)

Set `TPP_RECEIPT_MODE=local-reference` and `TPP_RECEIPT_ROOT=/absolute/receipt/root`
before starting `tpp-planner-service`. Enter receipt paths relative to that root, for
example `receipts/hotel-folio.pdf`. The exporter checks that the resolved path is a
readable file beneath the root, including symlink containment, and emits its absolute
`file:` URI. Absolute inputs, missing files, and traversal outside the root are rejected.
Python callers use `ExportService(receipt_delivery=ReceiptDelivery("local-reference",
root=Path("/absolute/receipt/root")))`.

These references do not expire and are not signatures, uploads, or web downloads.
Accounting must have filesystem access to the same file path; copy the receipts through
an approved shared filesystem if needed. A browser or spreadsheet may block `file:`
navigation: resolve the URI path locally instead. No external service is contacted.

### Hosted signed mode (explicit adapter)

Python callers construct `ReceiptDelivery("hosted-signed", origin="https://receipts.your-domain",
signer=sign_receipt, verifier=verify_receipt)` and pass its `ExportService` into
`create_app(store, export_service=service)`. Import `ReceiptDelivery` from
`travel_plan_permission.receipt_delivery`. Setting an environment mode alone cannot
supply a signer or verifier and therefore cannot enable hosted delivery.

The trusted signer accepts `(receipt_reference, expires_at)` and returns an HTTPS URL.
The independent verifier accepts `(url, receipt_reference, expires_at, now)` and must
validate the signature, receipt identity, and exact requested seven-day expiry before
returning true. Timestamp-only, tampered, expired, cross-origin, malformed, or placeholder
results must fail. The exporter also enforces HTTPS, origin equality, and rejection of
example-domain placeholders. Configuration adapters are trusted code; URL syntax alone
cannot prove a cryptographic signature.

The hosting operator must provide an authenticated receipt lookup, signing keys and
rotation, and a download endpoint that verifies identity/signature and rejects access
at or after expiry. IT must approve the receipt host, network access, and credentials.
This repository does not deploy that endpoint or upload receipts. Use local mode until
such an adapter exists. Export-time verification is not a substitute for endpoint checks.

Regression evidence: run
`PYTHONPATH=src python -m pytest tests/python/test_http_service.py::test_portal_receipt_delivery_configuration tests/python/test_export_service.py::test_receipt_link_requires_real_delivery_mode -q`.
The temporary-file and deterministic HMAC fixtures exercise resolved file bytes, hosted
verification before expiry, rejection after tampering/expiry, and portal validation
errors without placeholder output. Capture pytest output with the PR validation evidence.

## Limits and performance

* Batch exports support up to **100** expense reports.
* CSV output is UTF-8 encoded with a header row.
* Excel amounts are formatted with currency number formatting for rapid review.
* The expense portal is export-only for now; direct accounting-system writes remain out of scope.
