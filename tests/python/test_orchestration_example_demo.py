"""The `orchestration-demo` entry point, end to end.

`pyproject.toml` ships this module as a console script and `docs/langgraph_quickstart.md` tells a
reader to run `python -m travel_plan_permission.orchestration.example`. Nothing executed it, so a
change anywhere between argument parsing and spreadsheet writing could break the documented
command without a single test going red — the classic way an example rots.

The property worth the most here is the one `Issues.txt` records as a deliberate fix: when
`--minimal-json` is given, the canonical payload must reach the graph rather than being re-derived
ad hoc. That is observable without reaching into internals — canonical-only fields such as
`flight_pref_outbound.depart_time` and `hotel.name` stop appearing in the unfilled-mapping report.
Reverting to a plan-only conversion puts them back, so the assertion has teeth.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from travel_plan_permission.orchestration import example

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sample_trip_plan_minimal.json"


def _run(monkeypatch, capsys, *argv: str) -> str:
    monkeypatch.setattr("sys.argv", ["orchestration-demo", "--no-langgraph", *argv])
    assert example.main() == 0
    return capsys.readouterr().out


# ---------------------------------------------------------------------------------------------
# The documented command.
# ---------------------------------------------------------------------------------------------


def test_the_quickstart_command_runs_and_writes_a_spreadsheet(tmp_path, monkeypatch, capsys):
    """`python -m travel_plan_permission.orchestration.example` with no arguments."""
    output = tmp_path / "travel_request_example.xlsx"
    out = _run(monkeypatch, capsys, "--output", str(output))

    assert output.exists()
    assert output.stat().st_size > 0
    assert "Policy status:" in out
    assert str(output) in out


def test_the_built_in_sample_plan_reports_its_missing_policy_inputs(tmp_path, monkeypatch, capsys):
    """The sample plan is deliberately incomplete; the demo's job is to say so legibly.

    Printing a bare status and swallowing the diagnostics is the failure this pins — the demo
    exists to show a reader what the graph reports, not just that it returned.
    """
    out = _run(monkeypatch, capsys, "--output", str(tmp_path / "demo.xlsx"))

    assert "Missing policy inputs:" in out
    body = out.split("Missing policy inputs:", 1)[1].split("Unfilled mapping report:", 1)[0]
    rules = {entry["rule_id"] for entry in json.loads(body.strip())}
    assert "fare_comparison" in rules
    assert all("message" in entry for entry in json.loads(body.strip()))


# ---------------------------------------------------------------------------------------------
# The minimal-intake path, and the canonical data it must carry.
# ---------------------------------------------------------------------------------------------


def test_minimal_json_carries_canonical_fields_into_the_spreadsheet(tmp_path, monkeypatch, capsys):
    """`flight_pref_outbound.depart_time` and `hotel.name` live ONLY in the canonical payload.

    A conversion that keeps just the `TripPlan` loses them, and the only visible symptom is that
    they reappear in the unfilled-mapping report — which is what this asserts, in both directions.
    """
    with_canonical = _run(
        monkeypatch,
        capsys,
        "--minimal-json",
        str(FIXTURE),
        "--output",
        str(tmp_path / "minimal.xlsx"),
    )
    without = _run(monkeypatch, capsys, "--output", str(tmp_path / "sample.xlsx"))

    assert "flight_pref_outbound.depart_time" in without
    assert "hotel.name" in without

    assert "flight_pref_outbound.depart_time" not in with_canonical
    assert "hotel.name" not in with_canonical


def test_minimal_json_reaches_the_graph_as_a_canonical_plan(tmp_path, monkeypatch):
    """The keyword argument itself, so a regression is named at the boundary it crosses."""
    seen: dict[str, object] = {}
    real = example.run_policy_graph

    def spy(plan, **kwargs):
        seen.update(kwargs)
        return real(plan, **kwargs)

    monkeypatch.setattr(example, "run_policy_graph", spy)
    monkeypatch.setattr(
        "sys.argv",
        [
            "orchestration-demo",
            "--no-langgraph",
            "--minimal-json",
            str(FIXTURE),
            "--output",
            str(tmp_path / "demo.xlsx"),
        ],
    )
    assert example.main() == 0

    assert seen["canonical_plan"] is not None
    assert seen["prefer_langgraph"] is False


def test_no_langgraph_is_what_selects_the_fallback_graph(tmp_path, monkeypatch):
    """Without the flag the demo asks for LangGraph; the flag is the only thing that turns it off.

    Inverting the flag would make `--no-langgraph` a no-op, which no output difference reveals.
    """
    seen: dict[str, object] = {}
    real = example.run_policy_graph

    def spy(plan, **kwargs):
        seen.update(kwargs)
        return real(plan, **kwargs)

    monkeypatch.setattr(example, "run_policy_graph", spy)
    monkeypatch.setattr("sys.argv", ["orchestration-demo", "--output", str(tmp_path / "demo.xlsx")])
    assert example.main() == 0
    assert seen["prefer_langgraph"] is True


# ---------------------------------------------------------------------------------------------
# Overrides.
# ---------------------------------------------------------------------------------------------


def test_trip_id_and_origin_city_override_the_payload():
    plan_input = example._plan_input_from_minimal(FIXTURE, "TRIP-OVERRIDE", "Kansas City, MO")

    assert plan_input.plan.trip_id == "TRIP-OVERRIDE"
    assert plan_input.plan.origin_city == "Kansas City, MO"
    assert plan_input.canonical is not None


def test_an_absent_origin_city_leaves_the_payload_value_alone():
    """`--origin-city` is optional, so omitting it must not write None over a real value."""
    from_payload = example._plan_input_from_minimal(FIXTURE, "TRIP-A", None)
    overridden = example._plan_input_from_minimal(FIXTURE, "TRIP-A", "Kansas City, MO")

    assert overridden.plan.origin_city == "Kansas City, MO"
    assert from_payload.plan.origin_city != "Kansas City, MO"


def test_a_missing_minimal_payload_fails_at_the_read(tmp_path):
    with pytest.raises(FileNotFoundError):
        example._plan_input_from_minimal(tmp_path / "absent.json", "TRIP-A", None)


# ---------------------------------------------------------------------------------------------
# The failure the demo refuses to paper over.
# ---------------------------------------------------------------------------------------------


def test_a_graph_that_returns_no_policy_result_is_an_error_not_a_blank_line(tmp_path, monkeypatch):
    """Printing `Policy status: None` and returning 0 would report success for a run that did no
    policy evaluation at all."""

    class _State:
        policy_result = None
        policy_missing_inputs = None
        unfilled_mapping_report = None
        spreadsheet_path = None

    monkeypatch.setattr(example, "run_policy_graph", lambda *_a, **_k: _State())
    monkeypatch.setattr(
        "sys.argv",
        ["orchestration-demo", "--no-langgraph", "--output", str(tmp_path / "demo.xlsx")],
    )
    with pytest.raises(RuntimeError, match="No policy result"):
        example.main()
