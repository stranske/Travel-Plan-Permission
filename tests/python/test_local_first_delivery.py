"""Smoke tests for the local-first static policy report.

The local-first delivery path must work with no hosted service and no network:
these tests exercise ``scripts/render_policy_report.py`` end to end and assert
the rendered HTML is genuinely self-contained.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from travel_plan_permission.policy import PolicyEngine  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "render_policy_report.py"
FIXTURE = ROOT / "tests" / "fixtures" / "sample_trip_plan_minimal.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("render_policy_report", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def renderer():
    return _load_module()


def test_static_policy_report_is_self_contained_html(renderer, tmp_path: Path) -> None:
    """The report renders offline, states a verdict, and fetches nothing."""

    output = tmp_path / "policy-report.html"
    assert renderer.main([str(FIXTURE), str(output)]) == 0

    markup = output.read_text(encoding="utf-8")
    assert markup.startswith("<!doctype html>")

    # A verdict must be stated, and it must be one of the two real verdicts.
    assert any(
        f">{v}<" in markup
        for v in (renderer.VERDICT_COMPLIANT, renderer.VERDICT_BLOCKED)
    )

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
