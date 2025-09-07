# Travel Workflow Modernization — Staged Plan

## Purpose

Automate and make reproducible the preparation, approval, and reimbursement
of travel with a fast MVP that delivers 80–90% of the benefit before
perfection.

## Stages at a glance

- **Stage 0 — Repo scaffolding**: docs, schemas, labels, CODEOWNERS,
  branch rules.
- **Stage 1 — Excel Agent Bridge**: agent completes existing Itinerary and
  Expense spreadsheets; Policy‑Lite checks; no new UI.
- **Stage 2 — Workflow Lite**: lightweight portal for submit/approve,
  minimal receipts; exports for accounting.
- **Stage 3 — Agentic Verify**: pre‑approved providers, snapshot options,
  deterministic manager re‑check.
- **Stage 4 — Hardening**: policy‑as‑code, exceptions, SSO/RBAC,
  immutable audit.

## What’s in/out per stage

See `docs/workflows.md` and `docs/policy-lite-checklist.md` for current
scope and guardrails.

## Success metrics

- Minutes saved per itinerary vs baseline
- Back‑and‑forth count before approval
- First-pass Policy-Lite pass rate
- % of trips processed without manual spreadsheet edits
