# Contributing Guidelines

Thank you for helping improve this project! This document highlights key workflows and conventions for contributors.

## Documentation auto-merge policy

Small documentation-only pull requests can be automatically merged when they satisfy the guardrails below:

- Scope is limited to `docs/` or Markdown files (`*.md`). No code or configuration files can be part of the change.
- Total diff is under 50 changed lines (additions + deletions).
- All required CI checks and statuses are green.
- The pull request has been idle for at least one hour since the last update to allow human review.
- The `no-auto-merge` label opts a pull request out of automation at any time.

### How it works

- A scheduled workflow (`.github/workflows/auto-merge-docs.yml`) inspects open pull requests every 30 minutes and can also be triggered manually.
- Eligible pull requests are merged with a squash commit once all conditions are met.
- Each automated merge is recorded in an audit log issue labeled `auto-merge-audit`, and a confirmation comment is added to the merged pull request.

If you want to prevent auto-merge for a documentation PR, add the `no-auto-merge` label. If your change includes more than Markdown or exceeds the line threshold, it will be skipped automatically.
