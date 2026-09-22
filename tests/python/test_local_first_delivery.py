"""Smoke tests for the local-first static policy report.

The local-first delivery path must work with no hosted service and no network:
these tests exercise ``scripts/render_policy_report.py`` end to end and assert
the rendered HTML is genuinely self-contained.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from travel_plan_permission.canonical import load_trip_plan_input  # noqa: E402
from travel_plan_permission.policy import (  # noqa: E402
    PolicyEngine,
    PolicyResult,
    RuleOutcome,
    Severity,
)
from travel_plan_permission.policy_api import _context_from_plan  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "render_policy_report.py"
FIXTURE = ROOT / "tests" / "fixtures" / "sample_trip_plan_minimal.json"


def _load_module():
    """Load the standalone report command without invoking its CLI."""

    spec = importlib.util.spec_from_file_location("render_policy_report", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def renderer():
    """Share the standalone report module across the smoke tests."""

    return _load_module()


def test_static_policy_report_is_self_contained_html(renderer, tmp_path: Path) -> None:
    """The report renders offline, states a verdict, and fetches nothing."""

    output = tmp_path / "policy-report.html"
    assert renderer.main([str(FIXTURE), str(output)]) == 0

    markup = output.read_text(encoding="utf-8")
    assert markup.startswith("<!doctype html>")

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    plan = load_trip_plan_input(payload).plan
    expected = (
        "BLOCKED"
        if PolicyEngine.from_file().blocking_results(_context_from_plan(plan))
        else "COMPLIANT"
    )
    assert f'<span class="verdict verdict-{expected}">{expected}</span>' in markup

    # Ground truth comes from the PolicyEngine DIRECTLY, not from the script's own
    # evaluate_plan(). Deriving the expectation from the code under test would make
    # this assertion tautological: breaking evaluate_plan would change both sides
    # and the gate would still pass.
    engine_rule_ids = [
        str(rule["rule_id"]) for rule in PolicyEngine.from_file().describe_rules()
    ]
    assert engine_rule_ids, "policy engine exposes no rules"
    missing = [rule_id for rule_id in engine_rule_ids if rule_id not in markup]
    assert not missing, f"report omits policy rules: {missing}"

    # Self-contained: no external fetches of any kind.
    assert "http://" not in markup
    assert "https://" not in markup
    assert not re.search(r"<script\b", markup, re.IGNORECASE)
    assert not re.search(r'<link\b[^>]*rel=["\']?stylesheet', markup, re.IGNORECASE)
    assert not re.search(r"<img\b|<iframe\b", markup, re.IGNORECASE)


def test_cli_writes_non_empty_report_without_a_hosted_service(tmp_path: Path) -> None:
    """The documented command exits 0 and leaves a non-empty file on disk."""

    output = tmp_path / "policy-report.html"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), str(FIXTURE), str(output)],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert completed.returncode == 0, completed.stderr
    assert output.exists() and output.stat().st_size > 0


@pytest.mark.parametrize(
    ("severity", "outcome", "expected"),
    [
        (Severity.BLOCKING, RuleOutcome.FAILED, "BLOCKED"),
        (Severity.BLOCKING, RuleOutcome.MISSING_DATA, "BLOCKED"),
        (Severity.BLOCKING, RuleOutcome.PASSED, "COMPLIANT"),
        (Severity.ADVISORY, RuleOutcome.FAILED, "COMPLIANT"),
        (Severity.ADVISORY, RuleOutcome.MISSING_DATA, "COMPLIANT"),
    ],
)
def test_report_renders_exact_verdict(renderer, severity, outcome, expected) -> None:
    """Blocking failures and missing data must not render as compliant."""

    result = PolicyResult(
        rule_id="test-rule",
        severity=severity,
        passed=outcome == RuleOutcome.PASSED,
        message="policy result",
        outcome=outcome,
    )
    markup = renderer.render_html(object(), [result], source=FIXTURE)
    assert f'<span class="verdict verdict-{expected}">{expected}</span>' in markup


@pytest.mark.parametrize("payload", [[], "trip", None, 7, True])
def test_cli_rejects_non_object_json(payload, tmp_path: Path) -> None:
    """Invalid top-level shapes produce a usage error and no output file."""

    source = tmp_path / "invalid.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    output = tmp_path / "policy-report.html"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), str(source), str(output)],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert completed.returncode == 2
    assert "TripPlan JSON must be an object" in completed.stderr
    assert "Traceback" not in completed.stderr
    assert not output.exists()
