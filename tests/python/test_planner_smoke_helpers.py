"""Loading smoke fixtures and choosing a token, and the template lookup beside them.

Each of these fails in a way that produces a confusing downstream error rather than a clear one.
A fixture that is a JSON list instead of an object passes `json.loads` and then explodes on the
first `.get`; a token chosen for the wrong auth mode produces a 401 the smoke run reports as a
service failure; a template that cannot be found raises somewhere inside spreadsheet rendering.

All three name the problem at the point they detect it, which is what these tests pin.
"""

from __future__ import annotations

import argparse
import json

import pytest

from travel_plan_permission.planner_auth import PlannerAuthConfig, PlannerAuthMode
from travel_plan_permission.planner_smoke import (
    PlannerSmokeError,
    _load_fixture,
    _resolve_token,
)
from travel_plan_permission.policy_api import _default_template_path


def _config(mode: PlannerAuthMode, provider: str | None = "google") -> PlannerAuthConfig:
    return PlannerAuthConfig(
        base_url="https://tpp.example.com",
        oidc_provider=provider,
        auth_mode=mode,
        access_token_configured=False,
        bootstrap_secret_configured=True,
        bootstrap_ttl_seconds=3600,
        oidc_audience=None,
        oidc_role_map_configured=False,
        oidc_role_map={},
        oidc_subject_claim="sub",
        missing_config=(),
        invalid_config=(),
    )


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ("TPP_ACCESS_TOKEN", "TPP_BOOTSTRAP_SIGNING_SECRET"):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------------------------


def test_a_json_object_fixture_is_loaded(tmp_path):
    (tmp_path / "trip.json").write_text(json.dumps({"trip_id": "t-1"}), encoding="utf-8")
    assert _load_fixture(tmp_path, "trip.json") == {"trip_id": "t-1"}


def test_a_missing_fixture_names_the_path_it_looked_for(tmp_path):
    """A bare FileNotFoundError from deep in a smoke run says nothing about which fixture."""
    with pytest.raises(PlannerSmokeError) as excinfo:
        _load_fixture(tmp_path, "absent.json")
    assert "absent.json" in str(excinfo.value)
    assert "missing" in str(excinfo.value).lower()


@pytest.mark.parametrize("payload", ["[1, 2, 3]", '"a string"', "42", "null"])
def test_a_fixture_that_is_not_an_object_is_refused_at_the_read(tmp_path, payload):
    """These all parse as valid JSON and then fail on the first `.get` somewhere far away.

    Refusing at the read turns an AttributeError deep in a request builder into a message naming
    the file.
    """
    (tmp_path / "trip.json").write_text(payload, encoding="utf-8")
    with pytest.raises(PlannerSmokeError) as excinfo:
        _load_fixture(tmp_path, "trip.json")
    assert "must contain a JSON object" in str(excinfo.value)


# ---------------------------------------------------------------------------------------------
# Token selection, per auth mode.
# ---------------------------------------------------------------------------------------------


def test_an_explicit_token_wins_over_every_mode():
    """The operator passed `--token` on purpose; deriving one anyway ignores the instruction."""
    args = argparse.Namespace(token="explicit-token")
    assert _resolve_token(args, _config(PlannerAuthMode.OIDC)) == "explicit-token"


def test_static_mode_reads_the_access_token(monkeypatch):
    monkeypatch.setenv("TPP_ACCESS_TOKEN", "from-env")
    args = argparse.Namespace(token=None)
    assert _resolve_token(args, _config(PlannerAuthMode.STATIC_TOKEN)) == "from-env"


def test_static_mode_without_a_token_names_the_variable():
    """A smoke run that proceeds tokenless reports a 401 as a service failure, sending the reader
    to debug the wrong system."""
    args = argparse.Namespace(token=None)
    with pytest.raises(PlannerSmokeError) as excinfo:
        _resolve_token(args, _config(PlannerAuthMode.STATIC_TOKEN))
    assert "TPP_ACCESS_TOKEN" in str(excinfo.value)


def test_bootstrap_mode_without_a_provider_is_refused_by_name():
    """A bootstrap token carries a provider claim; minting one without a provider produces a
    token that fails audience validation for a reason the error would not mention."""
    args = argparse.Namespace(token=None)
    with pytest.raises(PlannerSmokeError) as excinfo:
        _resolve_token(args, _config(PlannerAuthMode.BOOTSTRAP_TOKEN, provider=None))
    assert "TPP_OIDC_PROVIDER" in str(excinfo.value)


@pytest.mark.parametrize("empty", ["", None])
def test_an_empty_explicit_token_falls_through_to_the_mode(empty, monkeypatch):
    """`--token ""` is not a token. Treating it as one sends an empty bearer."""
    monkeypatch.setenv("TPP_ACCESS_TOKEN", "from-env")
    args = argparse.Namespace(token=empty)
    assert _resolve_token(args, _config(PlannerAuthMode.STATIC_TOKEN)) == "from-env"


# ---------------------------------------------------------------------------------------------
# Template lookup.
# ---------------------------------------------------------------------------------------------


def test_the_repo_template_is_found():
    """The checkout path, which is what every developer and CI run actually hits."""
    path = _default_template_path()
    assert path.exists()
    assert path.parent.name == "templates"


def test_an_unknown_template_name_raises_rather_than_returning_a_missing_path():
    """Returning a path that does not exist defers the failure to whoever opens it, by which
    point the error names a temp directory instead of the template that was asked for."""
    with pytest.raises(FileNotFoundError) as excinfo:
        _default_template_path("no-such-template.xlsx")
    assert "no-such-template.xlsx" in str(excinfo.value)
