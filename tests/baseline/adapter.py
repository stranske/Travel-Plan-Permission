"""App-specific adapter for the Travel-Plan-Permission approval/policy surface.

This is the ONLY app-specific piece the shared ``baseline_kit`` needs: a way to
turn an input (here, a *request* scenario describing expense items plus a policy
context) into a flat ``dict[str, float|int]`` of named scalar outcomes.
Everything else -- directional checks, invariants, golden masters, the coverage
manifest -- is generic and lives in ``baseline_kit``.

Target surfaces (both deterministic: no DB, no network, no LLM):

* ``travel_plan_permission.approval.ApprovalEngine.evaluate_expense`` -- maps a
  single :class:`ExpenseItem` to an :class:`ApprovalDecision` (auto-approved /
  flagged / pending) by walking the ordered rules in ``config/approval_rules.yaml``.
  We run it over every expense in the scenario and also call
  ``evaluate_report`` to capture the report-level rollup status.
* ``travel_plan_permission.policy.PolicyEngine.validate`` -- maps a
  :class:`PolicyContext` to a list of :class:`PolicyResult` (per-rule pass/fail
  with blocking/advisory severity) using ``config/policy.yaml``.

Scenario model
--------------
The base request lives in ``catalog.yaml`` under ``base.request``. Each scenario
is the base request with an optional ``patch`` applied. A patch is an ordered
list of operations the small DSL ``apply_patch`` understands:

* ``{op: set_expense_amount, index: i, value: V}`` -- overwrite one expense's amount.
* ``{op: set_expense_category, index: i, value: cat}`` -- change one expense's category.
* ``{op: set_expense_description, index: i, value: text}`` -- change description
  (drives the ``non_reimbursable`` keyword rule).
* ``{op: add_expense, category, description, amount, expense_date?}`` -- append a row.
* ``{op: drop_expense, index: i}`` -- remove a row.
* ``{op: set_context, field: f, value: V}`` -- set a :class:`PolicyContext` field
  (dates parsed from ISO strings, money fields wrapped in ``Decimal``).
* ``{op: clear_context, field: f}`` -- set a context field back to ``None``.

This keeps the catalog declarative and the variants directionally predictable
(push an amount past a threshold -> flagged; add a blocked keyword -> a blocking
violation; comply with everything -> auto-approved, zero violations).

Output flattening
-----------------
We flatten the combined run to a single flat ``dict``:

Approval side (aggregated over the expense list)::

    approval.n_expenses
    approval.n_auto_approved
    approval.n_flagged
    approval.n_pending
    approval.all_auto_approved        (1/0)
    approval.any_flagged              (1/0)
    approval.requested_amount         (sum of expense amounts)
    approval.auto_approved_amount     (sum of amounts that auto-approved)
    approval.report_flagged           (1/0 from evaluate_report rollup)
    approval.report_auto_approved     (1/0 from evaluate_report rollup)

Policy side::

    policy.n_rules
    policy.n_passed
    policy.violation_count
    policy.blocking_violation_count
    policy.advisory_violation_count
    policy.<rule_id>.passed           (1/0 per rule)

Combined::

    requires_escalation               (1/0): any blocking policy violation OR
                                      any flagged expense.

Determinism note: ``evaluate_expense`` stamps a wall-clock ``timestamp`` on each
decision, but we never read it into the flat dict, so the output is stable.
"""

from __future__ import annotations

import copy
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

# PolicyContext fields that hold money and must be wrapped in Decimal.
_DECIMAL_CONTEXT_FIELDS = {
    "selected_fare",
    "lowest_fare",
    "driving_cost",
    "flight_cost",
}
# PolicyContext fields that hold ISO date strings in the catalog.
_DATE_CONTEXT_FIELDS = {"booking_date", "departure_date", "return_date"}


# ---------------------------------------------------------------------------
# Patch DSL
# ---------------------------------------------------------------------------


def _coerce_context_value(field: str, value: Any) -> Any:
    if value is None:
        return None
    if field in _DATE_CONTEXT_FIELDS:
        return date.fromisoformat(str(value))
    if field in _DECIMAL_CONTEXT_FIELDS:
        return Decimal(str(value))
    if field == "comparable_hotels":
        return [Decimal(str(v)) for v in value]
    return value


def apply_patch(base_request: dict[str, Any], patch: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Return a deep copy of ``base_request`` with ``patch`` operations applied."""
    request = copy.deepcopy(base_request)
    expenses: list[dict[str, Any]] = request.setdefault("expenses", [])
    context: dict[str, Any] = request.setdefault("context", {})

    for step in patch or []:
        op = step["op"]
        if op == "set_expense_amount":
            expenses[int(step["index"])]["amount"] = step["value"]
        elif op == "set_expense_category":
            expenses[int(step["index"])]["category"] = step["value"]
        elif op == "set_expense_description":
            expenses[int(step["index"])]["description"] = step["value"]
        elif op == "add_expense":
            expenses.append(
                {
                    "category": step["category"],
                    "description": step["description"],
                    "amount": step["amount"],
                    "expense_date": step.get("expense_date", "2025-01-05"),
                }
            )
        elif op == "drop_expense":
            del expenses[int(step["index"])]
        elif op == "set_context":
            context[step["field"]] = step["value"]
        elif op == "clear_context":
            context[step["field"]] = None
        else:  # pragma: no cover - guards against catalog typos
            raise ValueError(f"unknown patch op: {op!r}")
    return request


# ---------------------------------------------------------------------------
# Build typed inputs
# ---------------------------------------------------------------------------


def _build_expense_items(raw_expenses: list[dict[str, Any]]) -> list[Any]:
    from travel_plan_permission.models import ExpenseCategory, ExpenseItem

    items: list[Any] = []
    for raw in raw_expenses:
        items.append(
            ExpenseItem(
                category=ExpenseCategory(raw["category"]),
                description=raw["description"],
                amount=Decimal(str(raw["amount"])),
                expense_date=date.fromisoformat(str(raw["expense_date"])),
            )
        )
    return items


def _build_context(raw_context: dict[str, Any], expense_items: list[Any]) -> Any:
    from travel_plan_permission.policy import PolicyContext

    kwargs: dict[str, Any] = {}
    for field, value in raw_context.items():
        kwargs[field] = _coerce_context_value(field, value)
    # The non_reimbursable rule reads context.expenses; reuse the approval items
    # so the two surfaces share one expense list per scenario.
    kwargs.setdefault("expenses", expense_items)
    return PolicyContext(**kwargs)


# ---------------------------------------------------------------------------
# Compute + flatten
# ---------------------------------------------------------------------------


def run_scenario(scenario: dict[str, Any], base_request: dict[str, Any]) -> dict[str, float]:
    """Apply a scenario's patch, run both engines, flatten to scalar metrics.

    Deterministic: rule order is fixed by config; no wall-clock fields are read.
    """
    from travel_plan_permission.approval import ApprovalEngine
    from travel_plan_permission.models import ApprovalStatus, ExpenseReport
    from travel_plan_permission.policy import PolicyEngine, Severity

    request = apply_patch(base_request, scenario.get("patch"))
    expense_items = _build_expense_items(request["expenses"])
    context = _build_context(request["context"], expense_items)

    # --- Approval side ------------------------------------------------------
    approval_engine = ApprovalEngine.from_file()
    decisions = [approval_engine.evaluate_expense(item) for item in expense_items]

    n_auto = sum(1 for d in decisions if d.status == ApprovalStatus.AUTO_APPROVED)
    n_flagged = sum(1 for d in decisions if d.status == ApprovalStatus.FLAGGED)
    n_pending = sum(1 for d in decisions if d.status == ApprovalStatus.PENDING)
    requested_amount = sum((item.amount for item in expense_items), Decimal("0"))
    auto_approved_amount = sum(
        (
            item.amount
            for item, d in zip(expense_items, decisions, strict=True)
            if d.status == ApprovalStatus.AUTO_APPROVED
        ),
        Decimal("0"),
    )

    report = ExpenseReport(
        report_id="BASELINE-RPT",
        trip_id="BASELINE-TRIP",
        traveler_name="baseline",
        expenses=expense_items,
    )
    approval_engine.evaluate_report(report)

    # --- Policy side --------------------------------------------------------
    policy_engine = PolicyEngine.from_file()
    results = policy_engine.validate(context)

    n_passed = sum(1 for r in results if r.passed)
    violations = [r for r in results if not r.passed]
    blocking_violations = [r for r in violations if r.severity == Severity.BLOCKING]
    advisory_violations = [r for r in violations if r.severity == Severity.ADVISORY]

    flat: dict[str, float] = {
        # Approval rollups
        "approval.n_expenses": len(decisions),
        "approval.n_auto_approved": n_auto,
        "approval.n_flagged": n_flagged,
        "approval.n_pending": n_pending,
        "approval.all_auto_approved": int(bool(decisions) and n_auto == len(decisions)),
        "approval.any_flagged": int(n_flagged > 0),
        "approval.requested_amount": float(requested_amount),
        "approval.auto_approved_amount": float(auto_approved_amount),
        "approval.report_flagged": int(report.approval_status == ApprovalStatus.FLAGGED),
        "approval.report_auto_approved": int(
            report.approval_status == ApprovalStatus.AUTO_APPROVED
        ),
        # Policy rollups
        "policy.n_rules": len(results),
        "policy.n_passed": n_passed,
        "policy.violation_count": len(violations),
        "policy.blocking_violation_count": len(blocking_violations),
        "policy.advisory_violation_count": len(advisory_violations),
        # Combined escalation signal
        "requires_escalation": int(bool(blocking_violations) or n_flagged > 0),
    }
    # Per-rule pass flags (stable rule_id set from config).
    for r in results:
        flat[f"policy.{r.rule_id}.passed"] = int(r.passed)

    return flat


def metric_names() -> list[str]:
    """Stable list of flat metric keys (rule-specific keys resolved at runtime)."""
    return [
        "approval.n_expenses",
        "approval.n_auto_approved",
        "approval.n_flagged",
        "approval.n_pending",
        "approval.all_auto_approved",
        "approval.any_flagged",
        "approval.requested_amount",
        "approval.auto_approved_amount",
        "approval.report_flagged",
        "approval.report_auto_approved",
        "policy.n_rules",
        "policy.n_passed",
        "policy.violation_count",
        "policy.blocking_violation_count",
        "policy.advisory_violation_count",
        "requires_escalation",
    ]
