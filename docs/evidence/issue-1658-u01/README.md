# Issue 1658 U01 — manager decisions reach planner readback

Base: `origin/main` 243ee23e37268528c986dbe30d017005b1a2d80a. Python 3.12.2, venv off the synced volume.

| Step | Command | Result | Evidence |
|------|---------|--------|----------|
| Deliberate break (source changes in `http_service.py` + `planner_http_routes.py` stashed, new test kept) | `python -m pytest tests/python/test_portal_receipt_api.py -q -k typed_planner_readback` | 3 FAIL (status read back `draft`, not the decision) | `break-red.txt`, `break-red.xml` |
| Restored | `python -m pytest tests/python/test_portal_receipt_api.py -q` | 24 PASS | `green.txt`, `green.xml` |
| Related suites | `python -m pytest tests/python/test_http_service.py tests/python/test_planner_integration_contract.py tests/python/test_planner_client.py tests/python/test_cross_repo_smoke.py tests/python/test_portal_receipt_api.py -q` | 265 PASS | `related-suites.txt` |

These are local, in-process results. They are not hosted CI results and they do not prove process-level or two-app acceptance, which the separate live-service smoke candidate owns.
