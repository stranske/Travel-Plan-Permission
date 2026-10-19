# Generic planner routes and authoritative portal state

Bounded audit for issue #1671, on base `b2ffe194deb9106c05df5d8162aa6a01106ff949`. This inventories the six routes registered by
`src/travel_plan_permission/planner_http_routes.py` and the execution services
they reach. It does not certify a deployed service or a consumer integration.

## Existing owned repairs

- Owner-bound generic writes, F37: issue #1669, [PR #1678](https://github.com/stranske/Travel-Plan-Permission/pull/1678),
  merged as `a3c6d639f00bd4a3fe8915703b02eefe344d38e2`.
- Authoritative manager reads: issue #1658, [PR #1677](https://github.com/stranske/Travel-Plan-Permission/pull/1677),
  merged as `89b2048ac156b07de03ec89e40d692626c14a88d`.
- Receipt identity/persistence contract: [PR #1659](https://github.com/stranske/Travel-Plan-Permission/pull/1659),
  merged as `3010e3e39eb0ae039a1e648f957d8e87441d8e2a`.

These are lineage links, not new acceptance verdicts. This audit adds tests and
evidence; it does not duplicate those production changes.

## Complete route inventory

Paths below are relative to `/api/planner` except `/readyz`. All implementation
names are in `src/travel_plan_permission/`; all named tests are in
`tests/python/test_portal_receipt_api.py` unless another file is named.

| Route / entry | Producer → consumer and contract | Evidence / disposition |
| --- | --- | --- |
| `GET /readyz` / `readyz` | Runtime configuration → readiness response; no proposal, draft, owner or manager state. | `planner_http_routes.readyz` → `http_service._readiness_response`. Intentional non-authoritative diagnostic. |
| `GET /intake-requirements` / `intake_requirements` | VIEW-authorized caller → configured intake catalog; no execution lookup or mutation. | `get_intake_requirement_catalog`, called only after `_authorize_request`. Intentional catalog read, not approval evidence. |
| `GET /policy-snapshot` / `policy_snapshot` | VIEW-authorized request body → `remember_plan`, or `trip_id` → `lookup_trip_plan`, then pure `policy_api.get_policy_snapshot`. The trip-ID cache is not the execution/receipt authority. | New `test_generic_snapshot_cache_cannot_replace_portal_authority` actually writes a different same-trip cache payload through HTTP, verifies that it changed, then proves the execution snapshot and manager decision survive. Confirmed separation; no claim that this legacy cache is owner-scoped. |
| `POST /proposals` / `proposal_submission` | CREATE authorization → pure `submit_proposal` → serialized `record_submission(auth_context=...)` → persisted execution binding check before any replacement. | `test_bound_execution_rejects_conflicting_replay` and `test_foreign_overwrite_cannot_replace_bound_execution` cover exact/modified replay, omitted/forged `draft_id`, owner/foreign identity and restart. Confirmed; existing F37 repair retained. |
| `GET /proposals/{proposal_id}/executions/{execution_id}` / `proposal_status` | VIEW identity → `lookup_execution_projection` → matching proposal-ID check → request from stored submission → `poll_execution_status(projected.trip_plan, ...)`. | `test_manager_decision_reaches_typed_planner_readback`, new stale-cache control and foreign-owner checks. Confirmed manager status/history projection with immutable submitted content. |
| `GET /executions/{execution_id}/evaluation-result` / `evaluation_result` | Same authenticated projection → request from stored submission → `get_evaluation_result(projected.trip_plan, ...)`. | Same readback tests plus `test_exception_decision_reaches_typed_planner_readback`. Rejection becomes `non_compliant` when no exception requirements remain; approval is not a policy-compliance waiver. Confirmed. |

## Execution-service inventory

| Entry / state boundary | Trace and invariant | Evidence / disposition |
| --- | --- | --- |
| `PlannerProposalStore.remember_plan`, `lookup_trip_plan` | Copy and persist a plan keyed by trip ID; cannot mutate the separately keyed `StoredProposal`. | New stale-cache HTTP control before and after a real close/reopen. Intentional cache, not manager authority. |
| `record_submission`, `lookup_submission` | Stable execution ID → `preserve_bound_submission` before writes; copies stored plan/request/response; persistence failure restores prior state and pending outbox. | Replay/foreign-overwrite tests, snapshot-equality assertions and existing backend-failure controls. Confirmed bound write protection. |
| `PortalReceiptStoreMixin.lookup_execution_draft` | Find execution in persisted drafts' `submission_response`, not caller `request.payload`. Multiple matches → 409; missing reserved `portal-v1:` binding → 404. | `test_execution_reads_use_persisted_receipt_index`, `test_missing_bound_state_fails_closed_after_restart`. Confirmed; a payload `draft_id` is not ownership. |
| `preserve_bound_submission` | Bound receipt → authenticated owner check → exact saved trip/request comparison; foreign → 404, altered snapshot → 409, identical replay → retain original. Unbound legacy portal resubmission remains intentional. | Both receipt and legacy variants of conflicting replay; foreign overwrite and cross-instance race controls. Confirmed. |
| `lookup_execution_projection` | One serialized operation reads submission, bound draft, draft exceptions and manager review. Compare non-workflow fields before copying only status/history/exceptions onto a new plan. Snapshot mismatch → 409. | Manager/exception readback, `test_projection_rejects_mismatched_review_snapshot`, new stale-cache controls. Confirmed; stored submission stays unchanged. |
| `prepare_portal_receipt`, `lookup_portal_receipt` | Identity mode/provider/subject/namespace plus handoff ID → immutable version/content deduplication; caller-supplied form identity cannot supply ownership. | Owner-identity, OIDC namespace, conflicting retry and concurrent preparation tests. Confirmed. |
| `read_portal_receipt` | Under one store operation, read bound draft and manager review; wrong version → 409; absent/foreign → 404. | Receipt decision/restart, identity and version controls. Confirmed; a 5xx remains unavailable, not absent or approved. |
| `complete_portal_submission` | Owner check → preserve existing submitted bound receipt/review on retry; otherwise submit → persist execution/draft → create actual manager review. Failed/unavailable submission cannot create success. | `test_decision_is_not_reset_by_submission_retry`, `test_unaccepted_submission_cannot_create_request_or_review`. Confirmed. |
| `create_manager_review`, `lookup_manager_review_for_draft`, `apply_manager_review_action` | Existing portal submit/APPROVE-authorized manager route writes review status and attributed history. Generic endpoints never write a manager decision. | All three manager actions through real HTTP; tests verify manager attribution and receipt/readback agreement. Confirmed boundary. |
| `_submission_status_request`, `_evaluation_request` | Construct request identity from saved trip/proposal/version and selected execution, not a fresh planner payload. | Typed planner readback and explicit proposal-ID mismatch handling in the route. Confirmed source trace. |
| `policy_api.submit_proposal`, `poll_execution_status`, `get_evaluation_result`, `get_policy_snapshot` | Pure policy/response producers; no receipt repository access. HTTP/store callers must supply the authorized/projected plan. Status/evaluation validate trip and stable execution identity. | Source inspection plus actual route/client tests; independently disconnecting each route's projection demonstrates why this caller boundary matters. Confirmed. |
| `_serialized_store_operation`, `_persist_state`, `_load_state` | Reentrant instance lock plus backend `service_operation`; outer operation reloads persisted state, nested operations share that snapshot. State serialization includes submissions, receipt bindings, reviews and exceptions. | SQLite close/reopen and cross-instance retry tests. Confirmed for exercised SQLite backend; no live PostgreSQL claim. |

## Replay, concurrency and restart evidence

`test_cross_instance_foreign_overwrite_and_portal_retry_preserve_binding` races a
foreign generic overwrite against an owner portal retry using two actual stores
on the same SQLite path. Expected responses are 404 and 200; saved receipt,
review and execution remain unchanged. Concurrent receipt creation separately
proves deduplication. These do not establish an exhaustive linearizability proof
for every manager-write/read interleaving or a remote deployment.

`test_generic_snapshot_cache_cannot_replace_portal_authority` exercises approve,
reject and request_changes through the real manager endpoint, then writes a
stale plan through the generic policy-snapshot endpoint. It checks typed status,
evaluation, receipt decision, exact saved submission and foreign-owner 404s,
then repeats after closing the store and reopening the SQLite database. The
new test neither mocks authentication nor replaces HTTP/store methods.

## Validation and deliberate-break evidence

The delivery command is:

```sh
PYTHONPATH=src python -m pytest tests/python/test_portal_receipt_api.py -q
```

Use the repository-selected `.venv/bin/python`. Result: **46 passed**, including three new stale-cache/restart cases. No
production mutation is part of the deliverable.

For each read route separately, replace its `lookup_execution_projection(...)`
call with `(proposal_store.lookup_submission(execution_id), None)` in
`planner_http_routes.py`, retaining the new tests and the rest of the source.
Run the same command with
`-k test_generic_snapshot_cache_cannot_replace_portal_authority`:

| Actual source disconnection | Observed result |
| --- | --- |
| `proposal_status` projection bypass | 3 failed, 43 deselected; stale submitted status replaces the manager status/history. |
| `evaluation_result` projection bypass | 3 failed, 43 deselected; rejection/foreign-owner assertions detect the bypass. |
| Byte-identical route restoration, full named suite | 46 passed. |

Original and restored route-file SHA-256:
`4f90825f7b04a1cad5f7dea8ef7f8522ffeda977e5d38cc850e05bca68ebd59e`.
Raw command output and restoration proof are retained under
`~/.codex/automations/pd-workloop-resume/run-20261019T1100/` as
`tpp1671-proposal_status-red.txt`, `tpp1671-evaluation_result-red.txt`,
`tpp1671-restored-green.txt`, and `tpp1671-proof.json`.
Black and Ruff check the changed test file. The only delivered changes are this
report and tests. These local results do not substitute for current-head CI,
post-push review, merge or original-source post-merge verification.

## Findings returned for review

No additional confirmed production defect was found in this bounded execution
authority seam. The existing two owned repairs remain linked above. Unknowns
are live PostgreSQL behavior, hosted identity/deployment integration and
exhaustive manager-decision concurrency; the tests do not certify those. The
legacy shared trip-ID policy cache is deliberately treated as non-authoritative
here; this audit does not decide a broader cache privacy/authorization policy.
No new issue, authorization policy, receipt redesign or bundled production fix
is proposed or automatically filed.
