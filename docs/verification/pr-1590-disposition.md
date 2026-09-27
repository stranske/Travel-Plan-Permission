# PR #1590 deliberate-break disposition

Source issue: #1588<br>
Merged PR: #1590<br>
Final PR head: `d7b6212c98787e76d3a54b6ff271024035b460f9`<br>
Merge commit: `27ae36ae3b1808230cbea566b80edb0367451d77`

## Disposition

PR #1590's body describes two deliberate breaks (hard-coding the published trip
limit and publishing no budget rules), but it does not preserve the actual
failure and restored-pass console transcript. Historical console output cannot
be recovered from the PR record without inventing evidence.

The gate still exists on current `main`, so the transcript below is a **current
reproduction**, run on 2026-09-27 from `origin/main` at
`35da6660f42b68af203e7d7af3be22c3667ee6c4`. It is not represented as output
from the historical #1590 implementation run.

## Intentional failure

Surgical break: in
`src/travel_plan_permission/validation.py::PolicyValidator.published_budget_rules`,
replace `float(rule.trip_limit)` with the constant `5000.0`. This recreates the
hard-coded-limit defect named in PR #1590.

Command:

```text
PYTHONPATH=src python3 -m pytest tests/test_policy_snapshot_caps.py::test_the_published_limit_follows_the_configuration -q
```

Observed failure:

```text
collected 1 item

tests/test_policy_snapshot_caps.py F                                     [100%]

=================================== FAILURES ===================================
______________ test_the_published_limit_follows_the_configuration ______________
tests/test_policy_snapshot_caps.py:88: in test_the_published_limit_follows_the_configuration
    assert budget == {
E   AssertionError: assert {'rule_id': '...ging': 600.0}} == {'rule_id': '...ging': 600.0}}
E
E     Omitting 3 identical items, use -vv to show
E     Differing items:
E     {'max_trip_total_usd': 5000.0} != {'max_trip_total_usd': 1234.0}
E     Use -v to get more diff
=========================== short test summary info ============================
FAILED tests/test_policy_snapshot_caps.py::test_the_published_limit_follows_the_configuration
============================== 1 failed in 0.70s ===============================
```

## Restored pass

After restoring `float(rule.trip_limit)`, the same named gate passed:

```text
collected 1 item

tests/test_policy_snapshot_caps.py .                                     [100%]

============================== 1 passed in 0.61s ===============================
```

The complete focused file also passed:

```text
PYTHONPATH=src python3 -m pytest tests/test_policy_snapshot_caps.py -q

collected 5 items

tests/test_policy_snapshot_caps.py .....                                 [100%]

============================== 5 passed in 0.53s ===============================
```

No deliberate-break source change remains in the branch.

## Final merged check state

`gh pr checks 1590 -R stranske/Travel-Plan-Permission` reports successful final
product evidence for the merged head: `CodeRabbit`, `Cross-Repo Smoke
(trip-planner)`, `Gate / gate`, `Orchestration Tests (LangGraph)`, Python input,
Ruff, Python 3.12/3.13, mypy, backplane conformance, reference-run emission,
generated delivery seal, and `gate-summary` all pass. Conditional keepalive,
autofix, bot-handler, verifier-creation, and promotion jobs are skipped rather
than failed. The command reports no failing or pending context.
