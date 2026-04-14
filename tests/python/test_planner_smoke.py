from __future__ import annotations

import contextlib
import socket
import threading
import time

import uvicorn

from travel_plan_permission.planner_smoke import main


def _set_static_runtime_env(monkeypatch, *, base_url: str, provider: str = "google") -> None:
    monkeypatch.setenv("TPP_BASE_URL", base_url)
    monkeypatch.setenv("TPP_OIDC_PROVIDER", provider)
    monkeypatch.setenv("TPP_AUTH_MODE", "static-token")
    monkeypatch.setenv("TPP_ACCESS_TOKEN", "dev-token")
    monkeypatch.delenv("TPP_BOOTSTRAP_SIGNING_SECRET", raising=False)


@contextlib.contextmanager
def _run_live_service(port: int) -> str:
    base_url = f"http://127.0.0.1:{port}"
    config = uvicorn.Config(
        "travel_plan_permission.http_service:create_app",
        factory=True,
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.25)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                break
        time.sleep(0.05)
    else:
        server.should_exit = True
        thread.join(timeout=10)
        raise RuntimeError("Live planner HTTP service failed to start in time.")

    try:
        yield base_url
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_planner_smoke_main_succeeds_against_live_service(monkeypatch, capsys, unused_tcp_port: int) -> None:
    with _run_live_service(unused_tcp_port) as base_url:
        _set_static_runtime_env(monkeypatch, base_url=base_url)

        exit_code = main([])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Planner HTTP smoke passed" in captured.out
    assert "unauthorized probe" in captured.out


def test_planner_smoke_fails_when_service_is_not_ready(monkeypatch, capsys, unused_tcp_port: int) -> None:
    with _run_live_service(unused_tcp_port) as base_url:
        _set_static_runtime_env(monkeypatch, base_url=base_url, provider="github")

        exit_code = main([])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Planner service is not ready" in captured.err


def test_planner_smoke_requires_base_url(monkeypatch, capsys) -> None:
    monkeypatch.delenv("TPP_BASE_URL", raising=False)
    monkeypatch.setenv("TPP_AUTH_MODE", "static-token")
    monkeypatch.setenv("TPP_ACCESS_TOKEN", "dev-token")
    monkeypatch.setenv("TPP_OIDC_PROVIDER", "google")

    exit_code = main([])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Planner smoke needs a service URL" in captured.err


def test_planner_smoke_requires_repo_checkout_or_fixtures_override(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setenv("TPP_BASE_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv("TPP_AUTH_MODE", "static-token")
    monkeypatch.setenv("TPP_ACCESS_TOKEN", "dev-token")
    monkeypatch.setenv("TPP_OIDC_PROVIDER", "google")
    monkeypatch.setenv("TPP_PLANNER_FIXTURES_DIR", str(tmp_path / "missing-fixtures"))

    exit_code = main([])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Planner smoke fixtures are unavailable" in captured.err
