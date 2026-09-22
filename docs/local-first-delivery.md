# Local-first delivery (no hosted service)

## Why this path exists

The target work environment cannot host this repo's primary surface. From the
work-environment response
([`INFORMATION-REQUEST-RESPONSE.md` §F item 17, travel policy engine](https://github.com/stranske/Ready/blob/main/research-program/artifacts/work-bundle/INFORMATION-REQUEST-RESPONSE.md)),
the travel policy engine is ranked as **blocked by a hosting gap**:

> Nothing built in this environment today runs that way — every tool here is a local script,
> a COM-driven Office file, or a static HTML page opened locally; there is no server-hosted,
> database-backed application running anywhere I've seen.

Travel-Plan-Permission's primary surface today is `tpp-planner-service` (FastAPI + Uvicorn) at
`src/travel_plan_permission/http_service.py`, deployed via the Render blueprint in `render.yaml`.
That path stays supported. This document describes the delivery shapes that produce policy value
**without** standing up that service, so operators in the constrained environment have a path.

## Surface map

| Repo surface | Delivery shape | Needs a host? |
| --- | --- | --- |
| `tpp-planner-service` (`src/travel_plan_permission/http_service.py`) | Hosted HTTP API + portal | Yes — Uvicorn/Render |
| `fill-spreadsheet` CLI | Local script → Excel workbook | No |
| `scripts/render_policy_report.py` | Local script → static HTML report | No |

Both local-first shapes run as ordinary local scripts and write a file to disk — the two delivery
modes the target environment already supports.

## 1. Trip plan → Excel workbook (`fill-spreadsheet`)

The primary local-first workflow. It turns a TripPlan JSON file into a completed travel request
spreadsheet with no service running (see `README.md`, "CLI: Fill Travel Spreadsheet"):

```bash
fill-spreadsheet path/to/plan.json path/to/output.xlsx
```

`fill-spreadsheet --help` prints usage. The output is a normal `.xlsx` file, so it opens in the
COM-driven Office environment described in the work-environment response.

## 2. Trip plan → static policy report (`scripts/render_policy_report.py`)

When the question is *"does this trip pass policy?"* rather than *"fill my form"*, render a static
HTML report. It evaluates the plan against the same policy-lite rules the hosted service uses
(`PolicyEngine` in `src/travel_plan_permission/policy.py`) and writes one self-contained file:

```bash
python scripts/render_policy_report.py tests/fixtures/sample_trip_plan_minimal.json /tmp/policy-report.html
```

It prints the verdict and the output path, then exits 0. Open the result by double-clicking it — a
`file://` page with no server behind it.

The report accepts either payload shape the repo supports (canonical `"type": "trip"` documents and
internal `TripPlan` JSON), because it loads through `load_trip_plan_input` in
`src/travel_plan_permission/canonical.py`.

### What "self-contained" means here

The generated HTML embeds its own CSS and references nothing external: no `<script>`, no stylesheet
link, no image, and no `http://` or `https://` URL anywhere in the document. It renders identically
on a machine with no network. `tests/python/test_local_first_delivery.py` asserts each of those
properties, so the guarantee is enforced rather than merely documented.

### Verdict semantics

| Verdict | Meaning |
| --- | --- |
| `COMPLIANT` | No blocking rule failed or lacked the data to decide |
| `BLOCKED` | At least one `blocking`-severity rule reported `failed` or `missing_data` |

Advisory rules are always listed in the table but never change the verdict. `missing_data` counts as
blocking on purpose: an unanswerable blocking rule is not a pass.

## Verification

```bash
python -m pytest tests/python/test_local_first_delivery.py
```

The gate `test_static_policy_report_is_self_contained_html` renders the report and checks that every
rule the `PolicyEngine` exposes appears in the output, that a real verdict is stated, and that the
document fetches nothing. It reads its expected rule set from `PolicyEngine.describe_rules()`
directly rather than from the script under test — an expectation derived from the code under test
would still pass if that code were replaced with placeholder output.

## Non-goals

- This does not deprecate or replace `tpp-planner-service`; the hosted path remains for environments
  that support it.
- No new policy rules are introduced here. Both local-first shapes read the same `policy.yaml`
  configuration as the hosted service, so verdicts do not diverge by delivery shape.
