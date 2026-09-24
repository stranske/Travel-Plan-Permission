"""Exercise the Gate commit-status script against fork token failures.

Fork pull requests run with a read-only ``GITHUB_TOKEN``. The Gate must keep
the computed verdict visible when the status write is refused, while leaving
same-repository permission failures and unrelated errors loud.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
GATE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pr-00-gate.yml"
STEP_NAME = "Report Gate commit status"

RUNNER_JS = textwrap.dedent("""
    const fs = require('fs');
    const vm = require('vm');
    const src = fs.readFileSync(process.argv[2], 'utf8');

    function makeError(status, message) {
      const error = new Error(message);
      error.status = status;
      return error;
    }

    async function runCase({ headRepo, baseRepo, error, state }) {
      const warnings = [];
      const summaryWrites = [];
      const summaryRaw = [];
      const summaryStub = {
        addHeading() { return summaryStub; },
        addRaw(text) { summaryRaw.push(String(text)); return summaryStub; },
        async write() { summaryWrites.push('write'); },
      };
      const githubStub = {
        rest: {
          repos: {
            createCommitStatus: async () => { if (error) throw error; },
          },
        },
      };
      const sandbox = {
        process: {
          env: {
            STATE: state,
            DESCRIPTION: 'all checks passed',
            TARGET_URL: 'https://example.invalid/run',
          },
        },
        console: { log() {} },
        core: { warning: (message) => warnings.push(String(message)), summary: summaryStub },
        context: {
          repo: { owner: 'stranske', repo: 'Travel-Plan-Permission' },
          sha: 'basesha',
          payload: {
            pull_request: {
              head: { sha: 'headsha', repo: { full_name: headRepo } },
              base: { repo: { full_name: baseRepo } },
            },
          },
        },
        github: githubStub,
      };
      vm.createContext(sandbox);
      let threw = null;
      try {
        await vm.runInContext('(async () => {\\n' + src + '\\n})()', sandbox);
      } catch (error) {
        threw = {
          status: error.status === undefined ? null : error.status,
          message: String(error.message),
        };
      }
      return { warnings, summaryWrites: summaryWrites.length, summaryRaw, threw };
    }

    const FORK = {
      headRepo: 'outside-contributor/Travel-Plan-Permission',
      baseRepo: 'stranske/Travel-Plan-Permission',
    };
    const SAME = {
      headRepo: 'stranske/Travel-Plan-Permission',
      baseRepo: 'stranske/Travel-Plan-Permission',
    };

    (async () => {
      const outcomes = {
        fork_read_only: await runCase({
          ...FORK,
          state: 'success',
          error: makeError(403, 'Resource not accessible by integration'),
        }),
        same_repo_read_only: await runCase({
          ...SAME,
          state: 'success',
          error: makeError(403, 'Resource not accessible by integration'),
        }),
        fork_rate_limit: await runCase({
          ...FORK,
          state: 'success',
          error: makeError(403, 'API rate limit exceeded'),
        }),
        fork_server_error: await runCase({
          ...FORK,
          state: 'success',
          error: makeError(500, 'Internal server error'),
        }),
        happy_path: await runCase({ ...FORK, state: 'success', error: null }),
      };
      process.stdout.write(JSON.stringify(outcomes));
    })();
    """).strip()


def _extract_status_script() -> str:
    document = yaml.safe_load(GATE_WORKFLOW.read_text(encoding="utf-8"))
    for job in document["jobs"].values():
        for step in job.get("steps") or []:
            if step.get("name") == STEP_NAME:
                return str(step["with"]["script"])
    raise AssertionError(f"{GATE_WORKFLOW} no longer defines {STEP_NAME!r}")


@pytest.fixture(scope="module")
def outcomes(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    node = shutil.which("node")
    if node is None:  # pragma: no cover - depends on the host
        message = "node is required to execute the Gate github-script step"
        if os.environ.get("CI"):
            pytest.fail(message)
        pytest.skip(message)

    workdir = tmp_path_factory.mktemp("gate-status")
    step_path = workdir / "step.js"
    step_path.write_text(_extract_status_script(), encoding="utf-8")
    runner_path = workdir / "runner.js"
    runner_path.write_text(RUNNER_JS, encoding="utf-8")

    completed = subprocess.run(
        [node, str(runner_path), str(step_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return dict(json.loads(completed.stdout))


def test_fork_read_only_403_does_not_fail_the_gate(outcomes: dict[str, Any]) -> None:
    assert outcomes["fork_read_only"]["threw"] is None


def test_fork_read_only_403_reports_the_real_verdict(outcomes: dict[str, Any]) -> None:
    case = outcomes["fork_read_only"]
    warning = " ".join(case["warnings"])
    summary = " ".join(case["summaryRaw"])
    assert "read-only" in warning
    assert "'success'" in warning
    assert case["summaryWrites"] == 1
    assert "headsha" in summary
    assert "success" in summary
    assert "all checks passed" in summary


def test_same_repo_403_still_fails_the_gate(outcomes: dict[str, Any]) -> None:
    assert outcomes["same_repo_read_only"]["threw"]["status"] == 403


def test_rate_limit_403_keeps_its_own_path(outcomes: dict[str, Any]) -> None:
    case = outcomes["fork_rate_limit"]
    assert case["threw"] is None
    assert any("Rate limit" in warning for warning in case["warnings"])


def test_non_403_errors_still_fail_the_gate(outcomes: dict[str, Any]) -> None:
    assert outcomes["fork_server_error"]["threw"]["status"] == 500


def test_successful_status_write_is_silent(outcomes: dict[str, Any]) -> None:
    case = outcomes["happy_path"]
    assert case["threw"] is None
    assert case["warnings"] == []
    assert case["summaryWrites"] == 0
    assert case["summaryRaw"] == []
