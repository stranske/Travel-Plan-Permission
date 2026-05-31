# Travel-Plan-Permission app behavior baseline kit

Scenario-driven wiring / sensibility / regression tests built on the shared
**`baseline_kit`** package. Only the app-specific pieces live here.

## Requires

`baseline_kit` (the shared core) must be importable. It lives in
`stranske/Workflows` under `packages/app-baseline-kit`:

```bash
pip install "app-baseline-kit @ git+https://github.com/stranske/Workflows.git#subdirectory=packages/app-baseline-kit"
```

It is declared in this repo's `pyproject.toml` `[project.optional-dependencies]
dev`, so `pip install -e ".[dev]"` pulls it (plus `pytest-regressions`, whose
`num_regression` fixture needs `numpy` + `pandas`, already in `dev`).

## Target surfaces

Two **deterministic** evaluators (no DB / network / LLM):

- `travel_plan_permission.approval.ApprovalEngine.evaluate_expense` — walks the
  ordered rules in `config/approval_rules.yaml` and returns an
  `ApprovalDecision` (auto-approved / flagged / pending) per expense.
- `travel_plan_permission.policy.PolicyEngine.validate` — runs the 10 policy-lite
  rules in `config/policy.yaml` against a `PolicyContext`, returning per-rule
  pass/fail with blocking/advisory severity.

The adapter reads the **live config files** (`ApprovalEngine.from_file()` /
`PolicyEngine.from_file()`), so the goldens track the shipped policy, and a
config change that silently moves a threshold trips the golden diff.

## Layout

```
adapter.py                # request fixture + patch -> flat outcome dict (the only app glue)
catalog.yaml              # base request + scenario patches + directional checks
invariants.py             # approval/policy invariants -> baseline_kit.InvariantResult
test_golden.py            # golden master of each scenario's flattened outcomes
test_directional.py       # metamorphic checks (over-limit -> flagged, blocked keyword -> blocking...)
test_invariants.py        # invariants on base + every scenario
test_coverage_manifest.py # metric-key coverage -> docs/reports/baseline-coverage.md
```

## Scenario model

A *scenario* is the base request (`catalog.yaml` `base.request`: an expense list
plus a policy context) with an optional ordered `patch` applied. The patch DSL
(`adapter.apply_patch`) supports `set_expense_amount`, `set_expense_category`,
`set_expense_description`, `add_expense`, `drop_expense`, `set_context`,
`clear_context` — enough to make each variant directionally predictable (push an
amount past a threshold → flagged; add a blocked keyword → a blocking violation;
comply with everything → auto-approved, zero violations).

## Running

```bash
PYTHONHASHSEED=0 pytest tests/baseline/                            # full suite
pytest tests/baseline/test_golden.py --force-regen                # re-bless after an intended change
BASELINE_REFRESH_REPORT=1 pytest tests/baseline/test_coverage_manifest.py  # refresh report
```

## Invariants enforced

Approval side:

- counts are non-negative and partition the list:
  `n_auto_approved + n_flagged + n_pending == n_expenses`
- `any_flagged == 1 ⇔ n_flagged > 0`; `all_auto_approved == 1 ⇔ (n_expenses>0 and all auto)`
- `0 <= auto_approved_amount <= requested_amount`
- report rollup precedence: `report_flagged ⇔ any_flagged`;
  `report_auto_approved ⇒ all_auto_approved`; the two are mutually exclusive

Policy side:

- fixed rule set: `n_rules == 10`; `n_passed + violation_count == 10`
- severity partition: `blocking + advisory == violation_count`
- per-rule pass flags are 0/1 and sum to `n_passed`

Combined:

- `requires_escalation == 1 ⇔ (blocking_violation_count > 0 or n_flagged > 0)`
```
