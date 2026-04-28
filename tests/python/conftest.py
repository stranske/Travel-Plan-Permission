"""Test configuration for adding src to the import path."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC_PATH = ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))


@pytest.fixture(autouse=True)
def isolated_portal_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep default HTTP service state isolated across parallel test workers."""

    monkeypatch.setenv("TPP_PORTAL_STATE_PATH", str(tmp_path / "portal-runtime-state.json"))
