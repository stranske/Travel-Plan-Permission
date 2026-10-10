# Issue 1658 local acceptance evidence

The source-bound final Python suite passes, with 1343 JUnit cases, 0 failures, 0 errors and 7 skipped/expected-failure cases. Pytest's console separately reports ordinary skips, xfails and deselection. Measured package coverage: 92.05% (existing threshold 80%). The focused API suite passes 21 cases. Black/Ruff and Mypy pass for the changed files; the existing HTTP module size guard remains unchanged (2,461 lines).

Six actual production mutations yield the exact intended assertion RED and byte-identical restoration GREEN: unaccepted submission, foreign owner, changed snapshot, tenant namespace, decision retry and truthful preparation. Raw JUnit, console, hashes, commands and restoration controls are in `raw-proof.tar.gz`. `manifest.json` binds each product source/test/config and archive member. No mutation was left in the implementation checkout.

The archive also retains the historical full-suite tool-pin/module-size failures and extraction seam failures. They are superseded by `final-suite`, not counted as passes. Existing submission helper monkeypatch seams are preserved. Policy/transport response fault injection complements the real signed-bootstrap/OIDC ASGI authentication tests; authentication is never mocked.

Python 3.12.2 uses the existing readiness runtime plus an isolated overlay with the repository-pinned Ruff 0.16.10, Black 26.10.0 and Mypy 2.4.0. No shared environment pins were changed. Hosted checks/review timing, PostgreSQL, deployment and consumer end-to-end acceptance remain separate. Existing trip-planner1872 must pin the accepted producer commit and complete original1842 scope. See `docs/contracts/portal-receipt-v1.md`.
