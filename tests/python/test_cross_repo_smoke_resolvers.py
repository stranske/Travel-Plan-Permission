"""Resolving where smoke state lives and which token authenticates it.

Both resolvers decide something the live smoke run then acts on. Getting either wrong does not
produce an obvious error: the run writes its state somewhere nobody looks, or authenticates as
nobody in particular, and the smoke passes against the wrong thing.

`_resolve_state_path` carries the interesting rule. The portal reads its state path from an
environment variable while the CLI takes `--state-path`, and a run where those two disagree would
assert against a file the portal never wrote. It refuses rather than picking one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from travel_plan_permission.cross_repo_smoke import (
    _PORTAL_STATE_ENV_VAR,
    CrossRepoSmokeError,
    _resolve_planner_token,
    _resolve_state_path,
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in (_PORTAL_STATE_ENV_VAR, "TPP_PLANNER_TOKEN", "TPP_ACCESS_TOKEN"):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------------------------
# State path.
# ---------------------------------------------------------------------------------------------


def test_the_environment_wins_when_nothing_is_configured(monkeypatch, tmp_path):
    monkeypatch.setenv(_PORTAL_STATE_ENV_VAR, str(tmp_path / "state.json"))
    assert _resolve_state_path(None) == (tmp_path / "state.json").resolve()


def test_the_configured_path_is_used_when_the_environment_is_silent(tmp_path):
    assert _resolve_state_path(tmp_path / "state.json") == (tmp_path / "state.json").resolve()


def test_agreeing_sources_are_accepted(monkeypatch, tmp_path):
    """Same file, two spellings. Resolving both before comparing is what makes them agree."""
    target = tmp_path / "state.json"
    monkeypatch.setenv(_PORTAL_STATE_ENV_VAR, str(target))
    assert _resolve_state_path(target) == target.resolve()


def test_disagreeing_sources_are_refused_rather_than_ranked(monkeypatch, tmp_path):
    """THE RULE THIS FILE EXISTS FOR.

    The portal reads its state path from the environment; the CLI takes `--state-path`. If they
    point at different files, the smoke run asserts against a file the portal never wrote — and
    passes or fails for reasons unrelated to the code under test. Picking either one silently
    would make that outcome depend on which precedence somebody chose.
    """
    monkeypatch.setenv(_PORTAL_STATE_ENV_VAR, str(tmp_path / "from-env.json"))
    with pytest.raises(CrossRepoSmokeError) as excinfo:
        _resolve_state_path(tmp_path / "from-flag.json")
    assert _PORTAL_STATE_ENV_VAR in str(excinfo.value)
    assert "--state-path" in str(excinfo.value), "the message must name both sources"


def test_a_user_relative_path_is_expanded(monkeypatch):
    """`~` in an environment variable is a real thing operators type."""
    monkeypatch.setenv(_PORTAL_STATE_ENV_VAR, "~/tpp-state.json")
    resolved = _resolve_state_path(None)
    assert "~" not in str(resolved)
    assert resolved.is_absolute()


def test_with_neither_source_a_default_under_the_cwd_is_used(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    resolved = _resolve_state_path(None)
    assert resolved.is_absolute()
    assert str(resolved).startswith(str(tmp_path.resolve()))


def test_every_result_is_absolute(monkeypatch, tmp_path):
    """A relative path resolves differently depending on the working directory a step runs in,
    which is exactly how two halves of one smoke run end up disagreeing."""
    monkeypatch.chdir(tmp_path)
    assert _resolve_state_path(Path("relative.json")).is_absolute()


# ---------------------------------------------------------------------------------------------
# Planner token.
# ---------------------------------------------------------------------------------------------


def test_the_planner_token_is_read(monkeypatch):
    monkeypatch.setenv("TPP_PLANNER_TOKEN", "tok-1")
    assert _resolve_planner_token() == "tok-1"


def test_the_access_token_is_the_fallback(monkeypatch):
    monkeypatch.setenv("TPP_ACCESS_TOKEN", "tok-2")
    assert _resolve_planner_token() == "tok-2"


def test_the_planner_token_wins_over_the_access_token(monkeypatch):
    """Both are set in a real environment; the planner-specific one is the more precise intent."""
    monkeypatch.setenv("TPP_PLANNER_TOKEN", "planner")
    monkeypatch.setenv("TPP_ACCESS_TOKEN", "access")
    assert _resolve_planner_token() == "planner"


def test_surrounding_whitespace_is_stripped(monkeypatch):
    """A token copied out of a terminal carries a newline, and a bearer header with one is
    rejected by the server for reasons that look nothing like a whitespace problem."""
    monkeypatch.setenv("TPP_PLANNER_TOKEN", "  tok-3\n")
    assert _resolve_planner_token() == "tok-3"


@pytest.mark.parametrize("value", ["", "   ", "\n", "\t"])
def test_a_blank_token_is_refused_not_sent(monkeypatch, value):
    """An empty bearer authenticates as nobody. Sending it produces a 401 whose cause is invisible
    from the client side; refusing names the two variables that would fix it."""
    monkeypatch.setenv("TPP_PLANNER_TOKEN", value)
    with pytest.raises(CrossRepoSmokeError) as excinfo:
        _resolve_planner_token()
    assert "TPP_PLANNER_TOKEN" in str(excinfo.value)
    assert "TPP_ACCESS_TOKEN" in str(excinfo.value)


def test_no_token_at_all_is_refused():
    with pytest.raises(CrossRepoSmokeError):
        _resolve_planner_token()
