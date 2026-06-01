"""Travel-Plan-Permission app behavior baseline kit.

Built on the shared ``baseline_kit`` package -- this directory contains only the
app-specific pieces (adapter, catalog, invariant bounds). The generic harness
(directional engine, invariant assertion, golden glue, coverage manifest) is
imported from ``baseline_kit``, the same core the TMP / PAEM / trip-planner /
Counter_Risk kits use.

Target surfaces (both deterministic: no DB, no network, no LLM):
  * ``travel_plan_permission.approval.ApprovalEngine.evaluate_expense`` -- maps
    an expense item to an approval decision (auto-approved / flagged / pending).
  * ``travel_plan_permission.policy.PolicyEngine.validate`` -- maps a policy
    context to per-rule pass/fail results with blocking/advisory severity.

The adapter reduces a combined run to a flat ``dict[str, float|int]`` of
approval rollups, policy rollups, per-rule pass flags, and a combined
escalation signal.
"""
