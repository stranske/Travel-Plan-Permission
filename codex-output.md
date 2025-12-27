Added the policy API documentation with model examples, function signatures, and usage patterns, and linked it from the README to make it easy for orchestration developers to find and follow. The new doc in `docs/policy-api.md` focuses on the exact `TripPlan`, `PolicyCheckResult`, and `ReconciliationResult` shapes used by `src/travel_plan_permission/policy_api.py`, and includes error handling and edge cases. The README link lives in `README.md`.

- Created `docs/policy-api.md` with function docs, JSON examples, and Python usage snippets.
- Linked the new doc from `README.md`.

Tests and linting
- `npx markdownlint-cli2 "**/*.md" "!**/node_modules/**"` failed (no network access to fetch `markdownlint-cli2`).

If you want, I can rerun markdownlint once dependencies are available offline.