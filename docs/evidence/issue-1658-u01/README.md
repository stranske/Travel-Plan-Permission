# Issue 1658 U01 — manager decisions reach planner readback

Base: `origin/main` 243ee23e37268528c986dbe30d017005b1a2d80a. Python 3.12.2, venv off the synced volume.

| Step | Command | Result | Evidence |
|------|---------|--------|----------|
| Deliberate break (source changes in `http_service.py` + `planner_http_routes.py` stashed, new test kept) | `python -m pytest tests/python/test_portal_receipt_api.py -q -k typed_planner_readback` | 3 FAIL (status read back `draft`, not the decision) | `break-red.txt`, `break-red.xml` |
| Restored | `python -m pytest tests/python/test_portal_receipt_api.py -q` | 24 PASS | `green.txt`, `green.xml` |
| Related suites | `python -m pytest tests/python/test_http_service.py tests/python/test_planner_integration_contract.py tests/python/test_planner_client.py tests/python/test_cross_repo_smoke.py tests/python/test_portal_receipt_api.py -q` | 265 PASS | `related-suites.txt` |

These are local, in-process results. They are not hosted CI results and they do not prove process-level or two-app acceptance, which the separate live-service smoke candidate owns.


## Local HTTP process restart continuation (PR 1677)

Parent: `b52d061c9e34e4336c4b702dded68b4985e9511a`. Interpreter:
`/tmp/tpp-venv/bin/python` (Python 3.12.2, Anaconda); existing Uvicorn 0.54.0
and HTTPX 0.28.1. No dependencies were installed.

`tests/python/test_http_service.py::test_manager_decision_http_process_restart`
collects six cases: approve/reject/request_changes, each with and without a
pending exception. Each starts the production `create_app` factory in Uvicorn,
prepares/submits the synthetic handoff and records the manager decision through
serialized authenticated HTTP, stops and waits for that process, then starts a
second Uvicorn process sharing the same temporary SQLite file. HTTPX uses only
an owned short `/tmp` Unix-domain socket, with no TCP listener or external
provider. The second process verifies receipt/snapshot/proposal/execution
linkage, decision/status/attributed history and justification, exception
visibility, policy verdict/version/metadata, and unauthenticated/foreign-owner
denial. Pending exceptions remain `exception_required` even after rejection;
approval and request_changes preserve the existing policy verdict.

The focused command is recorded verbatim in `green-command.json` in the owning
lane evidence directory:
`~/.codex/orchestrator/measurement/issue-1677-http-restart/`.
It runs the six new cases, existing manager-decision/finalization and restart
HTTP cases, the exact module-size guard, and the receipt, planner-client and
integration-contract suites. Result: **75 passed, 1 deselected**. The deselected
OIDC test starts a TCP JWKS fixture and was deliberately excluded under this
continuation's UDS-only constraint; this is not an environment failure or a
claim of full-suite coverage. Ruff check/format and `git diff --check` pass.
`http_service.py` stays at 2461 lines with its unchanged 2470-line guard.

Causal check: temporarily replace the actual production projection's
`projected.approval_history` copy with an empty tuple. The named approve/no-exception
HTTP regression fails at `authoritative manager history survives HTTP restart`
(**1 failed**, on its pre-restart read). Restore byte-identically, then run the
focused GREEN above, which includes both process lifetimes in all six cases.
All tracked `src/` hashes before and after restoration match. The deliberate
failure proves the history projection binding; the unmodified two-process
GREEN independently proves durable HTTP restart readback.

`verification.json` records all 12 distinct final-suite child PIDs and matching
wait/reap receipts; every owned socket and its temporary directory is absent.
Readiness is bounded to 15 seconds with captured server logs; terminate/wait
and bounded kill/wait fallback target only the created child. All 12 Uvicorn
logs are preserved in the evidence directory.

The capability advisor consultation was attempted with `--surface opener-lane
--repository stranske/Travel-Plan-Permission` before validation, but the shared
`capabilities.json.lock` write was denied. A proposed use/decline receipt is in
`capability-proposed-receipt.json`; no shared receipt is claimed. Native attempts
38994855922:1 and 38999300863:1 were directly terminal with completed jobs, and
all paginated comments/reservations were refreshed before editing. Prior local
writer terminality comes from the parent's explicit recorded session evidence;
local `ps` inspection was denied. The detached network wrapper's launchd path
was denied and its built-in authenticated fallback succeeded.

These results prove local production HTTP/SQLite restart behavior. Hosted
current-head CI, independent review/provider acceptance, the review floor,
post-merge verification and full source acceptance remain separate gates.
No consumer two-app, deployment, hosting, or source-issue closure is claimed.

Evidence SHA-256:

| Artifact | SHA-256 |
|---|---|
| `green.log` | `df2a91b5ab06b7e902a7ff0aaca9f7afb97f0ba9c6d542e5b71343dbcf2006f4` |
| `green.xml` | `746a6eebdffe8da6d3c3c3a8d6e388be5cfeaab30f2d4c368e3dfd6a50f52c9b` |
| `red.log` | `4236dfcb58b2dc407974fd4fe940f34324525ff384fe9738835c6b06d9b7346c` |
| `red.xml` | `a866c736eeab4eeced06f965d2837c51acc527efd629f517dd0492f04a3b3adf` |
| `mutation.json` | `c005db512ad6dec65f5a73fe974649edc9a5127b433505e4110bd22d36cb7446` |
| `green-command.json` | `0ec8a7bad62db27915fc0ec2c73182da01b4fd099abde029373d3dae810ce342` |
