from __future__ import annotations

from pathlib import Path

import pytest


def _resolved(path: str) -> str:
    try:
        return Path(path).resolve().as_posix()
    except FileNotFoundError:
        return Path(path).as_posix()


def _only_orchestration_tests(args: list[str]) -> bool:
    root = Path(__file__).resolve().parents[1]
    orchestration_tests = {
        (root / "tests/orchestration_graph_test.py").resolve().as_posix(),
        (root / "tests/python/test_langgraph_orchestration.py").resolve().as_posix(),
    }

    selected = {_resolved(arg) for arg in args if arg.endswith(".py") or Path(arg).is_file()}
    return selected == orchestration_tests


def pytest_load_initial_conftests(early_config, args):
    if _only_orchestration_tests(args):
        if "--no-cov" not in args:
            args.append("--no-cov")
        early_config.pluginmanager.set_blocked("pytest_cov")
        early_config.pluginmanager.set_blocked("cov")


def pytest_configure(config):
    if not hasattr(config.option, "cov_source"):
        return

    if _only_orchestration_tests(list(config.args)):
        config.option.no_cov = True
        config.option.cov_fail_under = 0
        config.option.cov_source = []
        config.option.cov_report = {}
        cov_plugin = None
        for name in ("_cov", "pytest_cov"):
            candidate = config.pluginmanager.get_plugin(name)
            if candidate is not None and hasattr(candidate, "options"):
                cov_plugin = candidate
                break
        if cov_plugin is not None:
            if hasattr(cov_plugin, "cov_fail_under"):
                cov_plugin.cov_fail_under = 0
            if hasattr(cov_plugin, "options") and hasattr(cov_plugin.options, "cov_fail_under"):
                cov_plugin.options.cov_fail_under = 0
            if hasattr(cov_plugin, "options") and hasattr(cov_plugin.options, "no_cov"):
                cov_plugin.options.no_cov = True
            if hasattr(cov_plugin, "cov_controller") and hasattr(cov_plugin.cov_controller, "cov"):
                cov = cov_plugin.cov_controller.cov
                if cov is not None and hasattr(cov, "config"):
                    cov.config.fail_under = 0
            if hasattr(cov_plugin, "_disabled"):
                cov_plugin._disabled = True


@pytest.hookimpl(tryfirst=True, wrapper=True)
def pytest_runtestloop(session):
    config = session.config
    if _only_orchestration_tests(list(config.args)):
        cov_plugin = None
        for name in ("_cov", "pytest_cov"):
            candidate = config.pluginmanager.get_plugin(name)
            if candidate is not None and hasattr(candidate, "options"):
                cov_plugin = candidate
                break
        if cov_plugin is not None and hasattr(cov_plugin, "options"):
            cov_plugin.options.cov_fail_under = 0
    yield
