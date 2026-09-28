# PR #1639 deliberate-break disposition

Source issue: #1594<br>
Merged PR: #1639<br>
Final PR head: `dfc84e7bd61ae64c8ab6c03aeca12c5f78b0fcdb`<br>
Merge commit: `35da6660f42b68af203e7d7af3be22c3667ee6c4`

## Disposition

PR #1639 replaced an unvalidated `model_copy(update=...)` override with a
validated `TripPlan.model_validate(...)` reconstruction, but its durable record
did not preserve the deliberate-break console transcript required by issue
#1594. Historical console output cannot be recovered from the PR record without
inventing evidence.

The gate still exists on current `main`, so the transcript below is a **current
reproduction**, run on 2026-09-28 from `origin/main` at
`1647cec33d4e85503f39d3c134d128483b96470a`. It is not represented as output
from the historical #1639 implementation run.

## Baseline pass

Command:

```text
PYTHONPATH=src python3 -m pytest tests/python/test_minimal_conversion.py::test_trip_plan_from_minimal_validates_overrides -q
```

Observed result:

```text
collected 1 item

tests/python/test_minimal_conversion.py .                                [100%]

============================== 1 passed in 1.06s ===============================
```

## Intentional failure

Surgical break: in
`src/travel_plan_permission/conversion.py::trip_plan_from_minimal`, replace the
validated reconstruction:

```python
updated_data = plan_input.plan.model_dump()
updated_data.update(overrides)
return TripPlan.model_validate(updated_data)
```

with the prior unvalidated behavior:

```python
return plan_input.plan.model_copy(update=overrides)
```

The same named command exited 1 with the expected negative assertion:

```text
collected 1 item

tests/python/test_minimal_conversion.py F                                [100%]

=================================== FAILURES ===================================
_______________ test_trip_plan_from_minimal_validates_overrides ________________
tests/python/test_minimal_conversion.py:80: in test_trip_plan_from_minimal_validates_overrides
    with pytest.raises(ValidationError, match="trip_id"):
E   Failed: DID NOT RAISE ValidationError
=========================== short test summary info ============================
FAILED tests/python/test_minimal_conversion.py::test_trip_plan_from_minimal_validates_overrides
============================== 1 failed in 0.80s ===============================
```

## Restored pass

After restoring the exact validated implementation, the named gate passed:

```text
collected 1 item

tests/python/test_minimal_conversion.py .                                [100%]

============================== 1 passed in 0.69s ===============================
```

The complete focused file also passed:

```text
PYTHONPATH=src python3 -m pytest tests/python/test_minimal_conversion.py -q

collected 7 items

tests/python/test_minimal_conversion.py .......                          [100%]

============================== 7 passed in 0.69s ===============================
```

Committed branch cleanup proof:

```text
git diff --exit-code 1647cec33d4e85503f39d3c134d128483b96470a HEAD -- src/travel_plan_permission/conversion.py tests/python/test_minimal_conversion.py
```

The command exited 0 with no output, so no deliberate-break source or test
change remains in the committed branch history.

Local checkout checks (recorded separately from the branch claim):

```text
git diff --cached --exit-code -- src/travel_plan_permission/conversion.py tests/python/test_minimal_conversion.py
git diff --exit-code -- src/travel_plan_permission/conversion.py tests/python/test_minimal_conversion.py
```

Both commands exited 0 with no output on the closer verification worktree.
