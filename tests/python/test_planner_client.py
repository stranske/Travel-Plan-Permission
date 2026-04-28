from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from travel_plan_permission.planner_client import (
    PlannerHttpError,
    PlannerJsonResponse,
    PlannerMalformedResponseError,
    PlannerPollingTimeout,
    TravelPlanPermissionClient,
)

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "planner_integration"


class ScriptedTransport:
    def __init__(self, responses: list[PlannerJsonResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict[str, str], dict[str, object] | None, float]] = []

    def __call__(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        json_body: dict[str, object] | None,
        timeout: float,
    ) -> PlannerJsonResponse:
        self.calls.append((method, url, headers, json_body, timeout))
        return self.responses.pop(0)


def _operation_payload(
    *,
    operation: str = "poll_execution_status",
    submission_status: str = "pending",
    execution_state: str = "deferred",
    terminal: bool = False,
) -> dict[str, object]:
    return {
        "operation": operation,
        "submission_status": submission_status,
        "request_id": "req-949",
        "correlation_id": {"value": "corr-949", "issued_by": "trip-planner"},
        "transport_pattern": "deferred",
        "execution_status": {
            "state": execution_state,
            "terminal": terminal,
            "summary": "Proposal execution state.",
            "external_status": "200 OK",
            "poll_after_seconds": None if terminal else 1,
            "updated_at": "2026-04-27T00:00:00Z",
        },
        "result_payload": {
            "proposal_id": "proposal-123",
            "proposal_version": "proposal-v1",
            "execution_id": "exec-949",
            "raw_response": {"provider_status": execution_state},
        },
        "error": None,
        "retry": None,
        "received_at": "2026-04-27T00:00:01Z",
        "status_endpoint": ("GET /api/planner/proposals/proposal-123/executions/exec-949"),
    }


def _json_response(payload: object, *, status_code: int = 200) -> PlannerJsonResponse:
    return PlannerJsonResponse(
        status_code=status_code,
        body=payload,
        text=json.dumps(payload),
    )


def _client(
    transport: ScriptedTransport,
    *,
    sleeper: Callable[[float], None] | None = None,
) -> TravelPlanPermissionClient:
    if sleeper is not None:
        return TravelPlanPermissionClient(
            base_url="https://tpp.example.test/",
            token="planner-token",
            timeout=2.5,
            transport=transport,
            sleeper=sleeper,
        )
    return TravelPlanPermissionClient(
        base_url="https://tpp.example.test/",
        token="planner-token",
        timeout=2.5,
        transport=transport,
    )


def test_submit_proposal_returns_stable_ids_and_auth_header() -> None:
    transport = ScriptedTransport([_json_response(_operation_payload(operation="submit_proposal"))])
    client = _client(transport)

    result = client.submit_proposal(
        trip_plan={"trip_id": "TRIP-949"},
        request_payload={
            "trip_id": "TRIP-949",
            "proposal_id": "proposal-123",
            "proposal_version": "proposal-v1",
        },
    )

    assert result.result_payload["proposal_id"] == "proposal-123"
    assert result.result_payload["execution_id"] == "exec-949"
    method, url, headers, json_body, timeout = transport.calls[0]
    assert method == "POST"
    assert url == "https://tpp.example.test/api/planner/proposals"
    assert headers["Authorization"] == "Bearer planner-token"
    assert json_body is not None
    assert json_body["request"] == {
        "trip_id": "TRIP-949",
        "proposal_id": "proposal-123",
        "proposal_version": "proposal-v1",
    }
    assert timeout == 2.5


def test_polling_returns_terminal_response_without_dropping_body() -> None:
    terminal_payload = _operation_payload(
        submission_status="failed",
        execution_state="failed",
        terminal=True,
    )
    transport = ScriptedTransport(
        [
            _json_response(_operation_payload()),
            _json_response(terminal_payload),
        ]
    )
    sleep_calls: list[float] = []
    client = _client(transport, sleeper=sleep_calls.append)

    result = client.wait_for_terminal_status(
        proposal_id="proposal-123",
        execution_id="exec-949",
        max_attempts=2,
    )

    assert result.submission_status == "failed"
    assert result.execution_status is not None
    assert result.execution_status.terminal is True
    assert result.result_payload["raw_response"] == {"provider_status": "failed"}
    assert [call[0] for call in transport.calls] == ["GET", "GET"]
    assert sleep_calls == [1]


def test_polling_timeout_preserves_last_nonterminal_response() -> None:
    transport = ScriptedTransport(
        [
            _json_response(_operation_payload()),
            _json_response(_operation_payload(execution_state="running")),
        ]
    )
    sleep_calls: list[float] = []
    client = _client(transport, sleeper=sleep_calls.append)

    with pytest.raises(PlannerPollingTimeout) as exc_info:
        client.wait_for_terminal_status(
            proposal_id="proposal-123",
            execution_id="exec-949",
            max_attempts=2,
        )

    assert exc_info.value.attempts == 2
    assert exc_info.value.retryable is True
    assert exc_info.value.last_response is not None
    assert exc_info.value.last_response.execution_status is not None
    assert exc_info.value.last_response.execution_status.state == "running"
    assert sleep_calls == [1]


def test_http_errors_are_structured_and_retryable_only_when_safe() -> None:
    transport = ScriptedTransport(
        [_json_response({"detail": "Not authenticated"}, status_code=401)]
    )
    client = _client(transport)

    with pytest.raises(PlannerHttpError) as exc_info:
        client.poll_status(proposal_id="proposal-123", execution_id="exec-949")

    assert exc_info.value.status_code == 401
    assert exc_info.value.payload == {"detail": "Not authenticated"}
    assert exc_info.value.retryable is False


def test_malformed_response_raises_structured_error() -> None:
    transport = ScriptedTransport([_json_response({"unexpected": "shape"})])
    client = _client(transport)

    with pytest.raises(PlannerMalformedResponseError) as exc_info:
        client.submit_proposal(
            trip_plan={"trip_id": "TRIP-949"},
            request_payload={"proposal_id": "proposal-123"},
        )

    assert exc_info.value.payload == {"unexpected": "shape"}
    assert exc_info.value.retryable is False


def test_fetch_evaluation_result_parses_planner_contract_fixture() -> None:
    payload = json.loads(
        (FIXTURE_ROOT / "evaluation_result_compliant.json").read_text(encoding="utf-8")
    )
    transport = ScriptedTransport([_json_response(payload)])
    client = _client(transport)

    result = client.fetch_evaluation_result(execution_id="exec-10c6fb4730f2")

    assert result.execution_id == "exec-10c6fb4730f2"
    assert result.outcome == "compliant"
    assert result.policy_result.status == "pass"
