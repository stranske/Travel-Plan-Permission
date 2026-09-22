#!/usr/bin/env python3
"""Render a self-contained static policy report from a TripPlan JSON file.

This is the local-first delivery path: it evaluates a trip plan against the
policy-lite rules and writes a single HTML file to disk. Nothing is served and
nothing is fetched at render time, so the output opens from the filesystem in
environments that cannot host ``tpp-planner-service``.

See ``docs/local-first-delivery.md``.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = ROOT / "src"
if str(SRC_PATH) not in sys.path:  # pragma: no cover - import bootstrap
    sys.path.insert(0, str(SRC_PATH))

from travel_plan_permission.canonical import load_trip_plan_input  # noqa: E402
from travel_plan_permission.policy import (  # noqa: E402
    PolicyEngine,
    PolicyResult,
    RuleOutcome,
    Severity,
)
from travel_plan_permission.policy_api import _context_from_plan  # noqa: E402

VERDICT_COMPLIANT = "COMPLIANT"
VERDICT_BLOCKED = "BLOCKED"


def evaluate_plan(payload: dict[str, object]) -> tuple[object, list[PolicyResult]]:
    """Evaluate a canonical or internal TripPlan payload against policy rules."""

    plan = load_trip_plan_input(payload).plan
    engine = PolicyEngine.from_file()
    return plan, engine.validate(_context_from_plan(plan))


def verdict_for(results: Sequence[PolicyResult]) -> str:
    """BLOCKED when any blocking rule failed or lacked the data to decide."""

    blocking = [
        result
        for result in results
        if result.severity == Severity.BLOCKING
        and result.outcome in {RuleOutcome.FAILED, RuleOutcome.MISSING_DATA}
    ]
    return VERDICT_BLOCKED if blocking else VERDICT_COMPLIANT


def _row(result: PolicyResult) -> str:
    """Render one escaped policy-result table row."""

    return (
        "<tr>"
        f'<td class="rule">{html.escape(result.rule_id)}</td>'
        f'<td class="outcome outcome-{html.escape(result.outcome)}">'
        f"{html.escape(result.outcome)}</td>"
        f'<td class="severity">{html.escape(result.severity)}</td>'
        f'<td class="message">{html.escape(result.message)}</td>'
        "</tr>"
    )


def render_html(plan: object, results: Sequence[PolicyResult], *, source: Path) -> str:
    """Build a single self-contained HTML document with no external references."""

    verdict = verdict_for(results)
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%SZ")
    rows = "\n".join(_row(result) for result in results)
    traveler = html.escape(str(getattr(plan, "traveler_name", "") or "unknown"))
    destination = html.escape(str(getattr(plan, "destination", "") or "unknown"))
    trip_id = html.escape(str(getattr(plan, "trip_id", "") or "unknown"))

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Travel policy report — {trip_id}</title>
<style>
body {{ font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
        margin: 2rem auto; max-width: 60rem; padding: 0 1rem; color: #1a1a1a; }}
h1 {{ font-size: 1.4rem; margin-bottom: 0.2rem; }}
.verdict {{ display: inline-block; padding: 0.35rem 0.9rem; border-radius: 0.3rem;
            font-weight: 700; letter-spacing: 0.04em; }}
.verdict-COMPLIANT {{ background: #e3f5e6; color: #14532d; }}
.verdict-BLOCKED {{ background: #fdE4e4; color: #7f1d1d; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 1.2rem; }}
th, td {{ border: 1px solid #d4d4d4; padding: 0.45rem 0.6rem;
          text-align: left; vertical-align: top; font-size: 0.92rem; }}
th {{ background: #f4f4f5; }}
.outcome-failed, .outcome-missing_data {{ font-weight: 700; color: #7f1d1d; }}
.outcome-passed {{ color: #14532d; }}
.meta {{ color: #52525b; font-size: 0.88rem; }}
</style>
</head>
<body>
<h1>Travel policy report</h1>
<p class="meta">Trip <strong>{trip_id}</strong> &middot; {traveler} &middot; {destination}</p>
<p>Verdict: <span class="verdict verdict-{verdict}">{verdict}</span></p>
<table>
<thead><tr><th>Rule</th><th>Outcome</th><th>Severity</th><th>Detail</th></tr></thead>
<tbody>
{rows}
</tbody>
</table>
<p class="meta">Generated {generated} from {html.escape(source.name)} by
scripts/render_policy_report.py — evaluated locally, no hosted service.</p>
</body>
</html>
"""


def main(argv: Sequence[str] | None = None) -> int:
    """Read a trip plan and write its policy report to the requested path."""

    parser = argparse.ArgumentParser(description=__doc__ and __doc__.splitlines()[0])
    parser.add_argument(
        "plan", type=Path, help="TripPlan JSON file (canonical or internal)"
    )
    parser.add_argument("output", type=Path, help="destination .html file")
    args = parser.parse_args(argv)

    payload = json.loads(args.plan.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        parser.error("TripPlan JSON must be an object")
    plan, results = evaluate_plan(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        render_html(plan, results, source=args.plan), encoding="utf-8"
    )
    print(f"{verdict_for(results)} — wrote {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
