from __future__ import annotations

import contextlib
import secrets
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn

from travel_plan_permission.planner_auth import Permission, mint_bootstrap_token
from travel_plan_permission.planner_smoke import main


def _set_static_runtime_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    base_url: str,
    provider: str = "google",
) -> None:
    monkeypatch.setenv("TPP_BASE_URL", base_url)
    monkeypatch.setenv("TPP_OIDC_PROVIDER", provider)
    monkeypatch.setenv("TPP_AUTH_MODE", "static-token")
    monkeypatch.setenv("TPP_ACCESS_TOKEN", "dev-token")
    monkeypatch.delenv("TPP_BOOTSTRAP_SIGNING_SECRET", raising=False)


@contextlib.contextmanager
def _run_live_service() -> Iterator[str]:
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(("127.0.0.1", 0))
    server_socket.listen(2048)
    server: uvicorn.Server | None = None
    thread: threading.Thread | None = None
    try:
        port = int(server_socket.getsockname()[1])
        base_url = f"http://127.0.0.1:{port}"
        config = uvicorn.Config(
            "travel_plan_permission.http_service:create_app",
            factory=True,
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
        server = uvicorn.Server(config)
        thread = threading.Thread(
            target=server.run, kwargs={"sockets": [server_socket]}, daemon=True
        )
        thread.start()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.settimeout(0.25)
                if probe.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.05)
        else:
            raise RuntimeError("Live planner HTTP service failed to start in time.")

        yield base_url
    finally:
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(timeout=10)
        server_socket.close()


@contextlib.contextmanager
def _reserved_closed_port() -> Iterator[int]:
    reserved_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    reserved_socket.bind(("127.0.0.1", 0))
    try:
        yield int(reserved_socket.getsockname()[1])
    finally:
        reserved_socket.close()


def test_planner_smoke_main_succeeds_against_live_service(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with _run_live_service() as base_url:
        _set_static_runtime_env(monkeypatch, base_url=base_url)

        exit_code = main([])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Planner HTTP smoke passed" in captured.out
    assert "unauthorized probe" in captured.out


def test_planner_smoke_fails_when_service_is_not_ready(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with _run_live_service() as base_url:
        _set_static_runtime_env(monkeypatch, base_url=base_url, provider="github")

        exit_code = main([])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Planner service is not ready" in captured.err


def test_planner_smoke_requires_base_url(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("TPP_BASE_URL", raising=False)
    monkeypatch.setenv("TPP_AUTH_MODE", "static-token")
    monkeypatch.setenv("TPP_ACCESS_TOKEN", "dev-token")
    monkeypatch.setenv("TPP_OIDC_PROVIDER", "google")

    exit_code = main([])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Planner smoke needs a service URL" in captured.err


def test_planner_smoke_fails_when_fixture_override_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TPP_BASE_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv("TPP_AUTH_MODE", "static-token")
    monkeypatch.setenv("TPP_ACCESS_TOKEN", "dev-token")
    monkeypatch.setenv("TPP_OIDC_PROVIDER", "google")
    monkeypatch.setenv("TPP_PLANNER_FIXTURES_DIR", str(tmp_path / "missing-fixtures"))

    exit_code = main([])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Planner smoke fixtures are unavailable" in captured.err


def test_planner_smoke_fails_when_static_token_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("TPP_BASE_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv("TPP_AUTH_MODE", "static-token")
    monkeypatch.setenv("TPP_OIDC_PROVIDER", "google")
    monkeypatch.delenv("TPP_ACCESS_TOKEN", raising=False)

    exit_code = main([])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "TPP_ACCESS_TOKEN" in captured.err


def test_planner_smoke_fails_when_bootstrap_secret_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("TPP_BASE_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv("TPP_AUTH_MODE", "bootstrap-token")
    monkeypatch.setenv("TPP_OIDC_PROVIDER", "google")
    monkeypatch.delenv("TPP_BOOTSTRAP_SIGNING_SECRET", raising=False)

    exit_code = main([])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "TPP_BOOTSTRAP_SIGNING_SECRET" in captured.err


def test_planner_smoke_fails_when_auth_mode_is_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("TPP_BASE_URL", "http://127.0.0.1:9999")
    monkeypatch.delenv("TPP_AUTH_MODE", raising=False)
    monkeypatch.setenv("TPP_OIDC_PROVIDER", "google")
    monkeypatch.delenv("TPP_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("TPP_BOOTSTRAP_SIGNING_SECRET", raising=False)

    exit_code = main([])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "TPP_AUTH_MODE" in captured.err


def test_planner_smoke_fails_on_connection_refused(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """URLError (connection refused) surfaces as a smoke failure, not an exception."""
    with _reserved_closed_port() as port:
        monkeypatch.setenv("TPP_BASE_URL", f"http://127.0.0.1:{port}")
        monkeypatch.setenv("TPP_AUTH_MODE", "static-token")
        monkeypatch.setenv("TPP_ACCESS_TOKEN", "test-token")
        monkeypatch.setenv("TPP_OIDC_PROVIDER", "google")

        exit_code = main([])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "failed" in captured.err.lower()


def test_planner_smoke_succeeds_with_bootstrap_token_mode(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """bootstrap-token auth mode accepts an explicitly minted token.

    This mirrors the CI cross-repo-smoke job which mints a token before running the
    planner smoke command against a live service.
    """
    with _run_live_service() as base_url:
        signing_secret = secrets.token_hex(32)
        token = mint_bootstrap_token(
            subject="ci-cross-repo-smoke",
            permissions=(Permission.VIEW, Permission.CREATE),
            provider="google",
            secret=signing_secret,
            expires_in_seconds=900,
        )
        monkeypatch.setenv("TPP_BASE_URL", base_url)
        monkeypatch.setenv("TPP_AUTH_MODE", "bootstrap-token")
        monkeypatch.setenv("TPP_OIDC_PROVIDER", "google")
        monkeypatch.setenv("TPP_BOOTSTRAP_SIGNING_SECRET", signing_secret)
        monkeypatch.delenv("TPP_ACCESS_TOKEN", raising=False)

        exit_code = main(["--token", token])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Planner HTTP smoke passed" in captured.out
    assert "unauthorized probe" in captured.out
