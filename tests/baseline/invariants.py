"""Travel-Plan-Permission approval/policy invariants.

Properties that must hold for ANY request scenario, grounded in the actual
``ApprovalEngine`` / ``PolicyEngine`` logic (see ``src/travel_plan_permission/
approval.py`` and ``policy.py``) -- NOT generic placeholders:

Approval side
  * counts are non-negative integers and partition the expense list:
        n_auto_approved + n_flagged + n_pending == n_expenses
    (every decision lands in exactly one of AUTO_APPROVED / FLAGGED / PENDING).
  * the boolean rollups are 0/1 and consistent with the counts:
        any_flagged == 1  iff  n_flagged > 0
        all_auto_approved == 1  iff  (n_expenses > 0 and n_auto == n_expenses)
  * money is non-negative and bounded:
        0 <= auto_approved_amount <= requested_amount
  * report rollup matches evaluate_report's documented precedence:
        report_flagged == 1      iff  any_flagged
        report_auto_approved == 1 implies all_auto_approved
        report_flagged and report_auto_approved are mutually exclusive.

Policy side
  * the rule set is fixed by config:
        n_rules == 10  and  n_passed + violation_count == n_rules
  * severity partition (every violation is blocking OR advisory; the surface
    never emits "info" failures):
        blocking_violation_count + advisory_violation_count == violation_count
  * each per-rule flag is 0/1, and exactly ``n_passed`` of them are 1.

Combined
  * requires_escalation is 0/1 and fires exactly when there is a blocking policy
    violation OR a flagged expense:
        requires_escalation == 1  iff  (blocking_violation_count > 0 or n_flagged > 0)

The result type and assertion helper are shared
(``baseline_kit.InvariantResult`` / ``assert_invariants``).
"""

from __future__ import annotations

from typing import Any

from baseline_kit import InvariantResult

from . import adapter


def check_scenario(scenario: dict[str, Any], base_request: dict[str, Any]) -> list[InvariantResult]:
    """Run every invariant against one scenario's flattened metrics."""
    m = adapter.run_scenario(scenario, base_request)

    results: list[InvariantResult] = []

    def add(name: str, ok: bool, detail: str, severity: str = "error") -> None:
        results.append(InvariantResult(name, bool(ok), severity, detail))

    n_expenses = m["approval.n_expenses"]
    n_auto = m["approval.n_auto_approved"]
    n_flagged = m["approval.n_flagged"]
    n_pending = m["approval.n_pending"]

    # --- Approval: counts partition the expense list -----------------------
    add(
        "approval.counts_nonneg",
        n_auto >= 0 and n_flagged >= 0 and n_pending >= 0,
        f"auto={n_auto} flagged={n_flagged} pending={n_pending}",
    )
    add(
        "approval.counts_partition",
        n_auto + n_flagged + n_pending == n_expenses,
        f"{n_auto}+{n_flagged}+{n_pending} != {n_expenses}",
    )

    # --- Approval: boolean rollups are 0/1 and consistent ------------------
    any_flagged = m["approval.any_flagged"]
    all_auto = m["approval.all_auto_approved"]
    add("approval.any_flagged_bool", any_flagged in (0, 1), f"any_flagged={any_flagged}")
    add("approval.all_auto_bool", all_auto in (0, 1), f"all_auto_approved={all_auto}")
    add(
        "approval.any_flagged_matches_count",
        (any_flagged == 1) == (n_flagged > 0),
        f"any_flagged={any_flagged} n_flagged={n_flagged}",
    )
    add(
        "approval.all_auto_matches_count",
        (all_auto == 1) == (n_expenses > 0 and n_auto == n_expenses),
        f"all_auto={all_auto} n_auto={n_auto} n_expenses={n_expenses}",
    )

    # --- Approval: money bounds --------------------------------------------
    requested = m["approval.requested_amount"]
    auto_amount = m["approval.auto_approved_amount"]
    add("approval.requested_nonneg", requested >= 0, f"requested={requested}")
    add("approval.auto_amount_nonneg", auto_amount >= 0, f"auto_amount={auto_amount}")
    add(
        "approval.auto_amount_le_requested",
        auto_amount <= requested + 1e-9,
        f"auto_amount={auto_amount} requested={requested}",
    )

    # --- Approval: report rollup precedence --------------------------------
    report_flagged = m["approval.report_flagged"]
    report_auto = m["approval.report_auto_approved"]
    add(
        "approval.report_flagged_bool", report_flagged in (0, 1), f"report_flagged={report_flagged}"
    )
    add("approval.report_auto_bool", report_auto in (0, 1), f"report_auto={report_auto}")
    add(
        "approval.report_flagged_iff_any_flagged",
        (report_flagged == 1) == (any_flagged == 1),
        f"report_flagged={report_flagged} any_flagged={any_flagged}",
    )
    add(
        "approval.report_auto_implies_all_auto",
        report_auto == 0 or all_auto == 1,
        f"report_auto={report_auto} all_auto={all_auto}",
    )
    add(
        "approval.report_status_mutually_exclusive",
        not (report_flagged == 1 and report_auto == 1),
        f"report_flagged={report_flagged} report_auto={report_auto}",
    )

    # --- Policy: fixed rule set + pass/violation partition -----------------
    n_rules = m["policy.n_rules"]
    n_passed = m["policy.n_passed"]
    violations = m["policy.violation_count"]
    blocking = m["policy.blocking_violation_count"]
    advisory = m["policy.advisory_violation_count"]
    add("policy.rule_count_fixed", n_rules == 10, f"n_rules={n_rules}")
    add(
        "policy.pass_violation_partition",
        n_passed + violations == n_rules,
        f"{n_passed}+{violations} != {n_rules}",
    )
    add(
        "policy.severity_partition",
        blocking + advisory == violations,
        f"blocking={blocking} advisory={advisory} violations={violations}",
    )

    # --- Policy: per-rule flags are 0/1 and sum to n_passed ----------------
    rule_flags = {k: v for k, v in m.items() if k.startswith("policy.") and k.endswith(".passed")}
    add(
        "policy.per_rule_flags_binary",
        all(v in (0, 1) for v in rule_flags.values()),
        f"flags={rule_flags}",
    )
    add(
        "policy.per_rule_flags_sum_to_passed",
        sum(rule_flags.values()) == n_passed,
        f"sum={sum(rule_flags.values())} n_passed={n_passed}",
    )

    # --- Combined: escalation signal ---------------------------------------
    escalation = m["requires_escalation"]
    add("escalation_bool", escalation in (0, 1), f"requires_escalation={escalation}")
    add(
        "escalation_iff_blocking_or_flagged",
        (escalation == 1) == (blocking > 0 or n_flagged > 0),
        f"escalation={escalation} blocking={blocking} n_flagged={n_flagged}",
    )

    return results
