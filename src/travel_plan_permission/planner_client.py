"""Client for the planner-facing Travel-Plan-Permission HTTP transport."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib import error, request

from .policy_api import (
    PlannerProposalEvaluationResult,
    PlannerProposalOperationResponse,
)

JsonPayload = dict[str, object]


@dataclass(frozen=True)
class PlannerJsonResponse:
    """Raw JSON response returned by the planner transport layer."""

    status_code: int
    body: Any
    text: str


Transport = Callable[[str, str, dict[str, str], JsonPayload | None, float], PlannerJsonResponse]


class PlannerTransportError(RuntimeError):
    """Base exception for planner transport failures."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        payload: object | None = None,
        text: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload
        self.text = text
        self.retryable = retryable


class PlannerHttpError(PlannerTransportError):
    """Raised when the service returns a non-success HTTP status."""


class PlannerMalformedResponseError(PlannerTransportError):
    """Raised when the service response cannot be parsed as the expected model."""


class PlannerPollingTimeout(PlannerTransportError):
    """Raised when bounded polling never reaches a terminal execution state."""

    def __init__(
        self,
        message: str,
        *,
        attempts: int,
        last_response: PlannerProposalOperationResponse | None,
    ) -> None:
        super().__init__(message, retryable=True)
        self.attempts = attempts
        self.last_response = last_response


def urllib_transport(
    method: str,
    url: str,
    headers: dict[str, str],
    json_body: JsonPayload | None,
    timeout: float,
) -> PlannerJsonResponse:
    """Issue a JSON HTTP request using the Python standard library."""

    encoded_body = None
    request_headers = dict(headers)
    if json_body is not None:
        encoded_body = json.dumps(json_body).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    req = request.Request(url, data=encoded_body, headers=request_headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            status_code = response.status
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        status_code = exc.code
    except error.URLError as exc:
        raise PlannerTransportError(
            f"{method} {url} failed: {exc.reason}",
            retryable=True,
        ) from exc

    body: Any = None
    if raw:
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = raw
    return PlannerJsonResponse(status_code=status_code, body=body, text=raw)


class TravelPlanPermissionClient:
    """Typed client for planner proposal submission and result polling."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout: float = 10.0,
        transport: Transport = urllib_transport,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        if not token:
            raise ValueError("token is required")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._transport = transport
        self._headers = {"Authorization": f"Bearer {token}"}

    def submit_proposal(
        self,
        *,
        trip_plan: JsonPayload,
        request_payload: JsonPayload,
    ) -> PlannerProposalOperationResponse:
        payload = self._request_json(
            "POST",
            "/api/planner/proposals",
            json_body={"trip_plan": trip_plan, "request": request_payload},
            step="proposal submission",
        )
        return self._parse_operation(payload, step="proposal submission")

    def poll_status(
        self,
        *,
        proposal_id: str,
        execution_id: str,
    ) -> PlannerProposalOperationResponse:
        payload = self._request_json(
            "GET",
            f"/api/planner/proposals/{proposal_id}/executions/{execution_id}",
            json_body=None,
            step="proposal status",
        )
        return self._parse_operation(payload, step="proposal status")

    def fetch_evaluation_result(
        self,
        *,
        execution_id: str,
    ) -> PlannerProposalEvaluationResult:
        payload = self._request_json(
            "GET",
            f"/api/planner/executions/{execution_id}/evaluation-result",
            json_body=None,
            step="evaluation result",
        )
        try:
            return PlannerProposalEvaluationResult.model_validate(payload)
        except ValueError as exc:
            raise PlannerMalformedResponseError(
                f"evaluation result returned malformed response: {payload!r}",
                payload=payload,
                retryable=False,
            ) from exc

    def wait_for_terminal_status(
        self,
        *,
        proposal_id: str,
        execution_id: str,
        max_attempts: int = 3,
    ) -> PlannerProposalOperationResponse:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        last_response: PlannerProposalOperationResponse | None = None
        for _ in range(max_attempts):
            last_response = self.poll_status(
                proposal_id=proposal_id,
                execution_id=execution_id,
            )
            execution_status = last_response.execution_status
            if execution_status is not None and execution_status.terminal:
                return last_response
            if last_response.submission_status in {"succeeded", "failed", "unavailable"}:
                return last_response
        raise PlannerPollingTimeout(
            "proposal status polling did not reach a terminal state",
            attempts=max_attempts,
            last_response=last_response,
        )

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: JsonPayload | None,
        step: str,
    ) -> JsonPayload:
        url = f"{self.base_url}{path}"
        response = self._transport(method, url, self._headers, json_body, self.timeout)
        if response.status_code < 200 or response.status_code >= 300:
            raise PlannerHttpError(
                f"{step} failed with HTTP {response.status_code}",
                status_code=response.status_code,
                payload=response.body,
                text=response.text,
                retryable=response.status_code >= 500 or response.status_code == 429,
            )
        if not isinstance(response.body, dict):
            raise PlannerMalformedResponseError(
                f"{step} returned non-object JSON",
                status_code=response.status_code,
                payload=response.body,
                text=response.text,
                retryable=False,
            )
        return response.body

    def _parse_operation(
        self,
        payload: JsonPayload,
        *,
        step: str,
    ) -> PlannerProposalOperationResponse:
        try:
            return PlannerProposalOperationResponse.model_validate(payload)
        except ValueError as exc:
            raise PlannerMalformedResponseError(
                f"{step} returned malformed response: {payload!r}",
                payload=payload,
                retryable=False,
            ) from exc
