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


def _pick_free_port() -> int:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return int(sock.getsockname()[1])


@contextlib.contextmanager
def _run_live_service() -> str:
    port = _pick_free_port()
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


def test_planner_smoke_main_succeeds_against_live_service(monkeypatch, capsys) -> None:
    with _run_live_service() as base_url:
        _set_static_runtime_env(monkeypatch, base_url=base_url)

        exit_code = main([])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Planner HTTP smoke passed" in captured.out
    assert "unauthorized probe" in captured.out


def test_planner_smoke_fails_when_service_is_not_ready(monkeypatch, capsys) -> None:
    with _run_live_service() as base_url:
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
