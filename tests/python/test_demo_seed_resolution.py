"""Locating demo fixtures, and refusing to mint a token that could never validate.

`mint_demo_reviewer_token` carries the contract worth pinning: it returns None when the service is
not in bootstrap-token mode, because that is the only mode able to VALIDATE a minted token.
Returning a token anyway would hand a demo operator a bearer that fails every request with a
generic 401 — a broken token is worse than an honest absence, since the absence can be explained
and the 401 cannot.

`demo_fixture_dir` is the other half: every way of failing to find fixtures names what to set.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from travel_plan_permission.demo_seed import (
    CANONICAL_TRIP_FIXTURE,
    DEMO_FIXTURE_DIR_ENV_VAR,
    DEMO_REVIEWER_SUBJECT,
    DemoSeedError,
    _load_fixture,
    _repo_fixture_dir,
    demo_fixture_dir,
    mint_demo_reviewer_token,
)
from travel_plan_permission.planner_auth import (
    PlannerAuthConfig,
    PlannerAuthMode,
    _parse_bootstrap_token,
)

SECRET = "a-demo-signing-secret-long-enough"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in (DEMO_FIXTURE_DIR_ENV_VAR, "TPP_BOOTSTRAP_SIGNING_SECRET"):
        monkeypatch.delenv(var, raising=False)


def _config(mode: PlannerAuthMode, provider: str = "google") -> PlannerAuthConfig:
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


# ---------------------------------------------------------------------------------------------
# Minting: an honest absence beats a broken bearer.
# ---------------------------------------------------------------------------------------------


def test_a_token_is_minted_in_bootstrap_mode(monkeypatch):
    monkeypatch.setenv("TPP_BOOTSTRAP_SIGNING_SECRET", SECRET)
    token = mint_demo_reviewer_token(_config(PlannerAuthMode.BOOTSTRAP_TOKEN))
    assert token is not None
    claims = _parse_bootstrap_token(token, secret=SECRET)
    assert claims.sub == DEMO_REVIEWER_SUBJECT


@pytest.mark.parametrize("mode", [PlannerAuthMode.STATIC_TOKEN, PlannerAuthMode.OIDC])
def test_no_token_is_minted_in_a_mode_that_could_not_validate_it(monkeypatch, mode):
    """The contract. Bootstrap mode is the only one that can verify a minted token.

    Handing back a bearer the service will reject gives a demo operator a generic 401 with no
    explanation; returning None lets the caller say WHY there is no token.
    """
    monkeypatch.setenv("TPP_BOOTSTRAP_SIGNING_SECRET", SECRET)
    assert mint_demo_reviewer_token(_config(mode)) is None


def test_no_token_is_minted_without_a_signing_secret():
    """Minting with an absent secret would produce a signature nothing can check."""
    assert mint_demo_reviewer_token(_config(PlannerAuthMode.BOOTSTRAP_TOKEN)) is None


def test_the_minted_token_carries_the_configured_provider(monkeypatch):
    monkeypatch.setenv("TPP_BOOTSTRAP_SIGNING_SECRET", SECRET)
    token = mint_demo_reviewer_token(_config(PlannerAuthMode.BOOTSTRAP_TOKEN, provider="okta"))
    assert _parse_bootstrap_token(token, secret=SECRET).provider == "okta"


def test_a_missing_provider_falls_back_rather_than_minting_a_blank_one(monkeypatch):
    """A token with an empty provider claim fails audience checks in a way that reads as a
    configuration bug rather than a missing field."""
    monkeypatch.setenv("TPP_BOOTSTRAP_SIGNING_SECRET", SECRET)
    # Built with provider=None directly. The first draft mutated a frozen dataclass through a
    # conditional `object.__setattr__`, which is both unreadable and one typo away from being a
    # silent no-op that tests nothing — `dataclasses.replace` states the intent and cannot
    # quietly skip.
    config = dataclasses.replace(_config(PlannerAuthMode.BOOTSTRAP_TOKEN), oidc_provider=None)
    token = mint_demo_reviewer_token(config)
    assert token is not None
    assert _parse_bootstrap_token(token, secret=SECRET).provider == "google"


# ---------------------------------------------------------------------------------------------
# Fixture resolution: every failure names what to set.
# ---------------------------------------------------------------------------------------------


def test_the_override_is_used_when_it_points_at_a_directory(monkeypatch, tmp_path):
    monkeypatch.setenv(DEMO_FIXTURE_DIR_ENV_VAR, str(tmp_path))
    assert demo_fixture_dir() == tmp_path


def test_a_user_relative_override_is_expanded(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "fixtures").mkdir()
    monkeypatch.setenv(DEMO_FIXTURE_DIR_ENV_VAR, "~/fixtures")
    assert demo_fixture_dir() == tmp_path / "fixtures"


def test_an_override_that_is_not_a_directory_is_refused_by_name(monkeypatch, tmp_path):
    """Falling back to the repo fixtures here would silently ignore what the operator asked for
    and seed a demo from the wrong data."""
    missing = tmp_path / "nope"
    monkeypatch.setenv(DEMO_FIXTURE_DIR_ENV_VAR, str(missing))
    with pytest.raises(DemoSeedError) as excinfo:
        demo_fixture_dir()
    assert DEMO_FIXTURE_DIR_ENV_VAR in str(excinfo.value)
    assert "nope" in str(excinfo.value), "the rejected value must appear in the message"


def test_the_repo_fixtures_are_found_without_an_override():
    """The checkout path, which is what a developer running the demo actually hits."""
    assert demo_fixture_dir() == _repo_fixture_dir()


def test_a_missing_fixture_file_names_the_path(monkeypatch, tmp_path):
    monkeypatch.setenv(DEMO_FIXTURE_DIR_ENV_VAR, str(tmp_path))
    with pytest.raises(DemoSeedError) as excinfo:
        _load_fixture(CANONICAL_TRIP_FIXTURE)
    assert CANONICAL_TRIP_FIXTURE in str(excinfo.value)


def test_a_fixture_is_loaded_as_a_mapping(monkeypatch, tmp_path):
    monkeypatch.setenv(DEMO_FIXTURE_DIR_ENV_VAR, str(tmp_path))
    (tmp_path / CANONICAL_TRIP_FIXTURE).write_text(json.dumps({"trip_id": "t-1"}), encoding="utf-8")
    assert _load_fixture(CANONICAL_TRIP_FIXTURE) == {"trip_id": "t-1"}
