from __future__ import annotations

import json

import httpx
import pytest

from travel_plan_permission.cross_repo_smoke import CrossRepoSmokeError, portal_transport


def test_form_transport_preserves_redirect_and_non_json_body() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(303, headers={"Location": "/receipt"}, text="approved")

    response = portal_transport(
        "POST",
        "http://portal.test/decision",
        {
            "Authorization": "Bearer synthetic-token",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        {"action": "approve", "note": "ready & checked", "count": 2},
        1.0,
        http_transport=httpx.MockTransport(respond),
    )

    assert response.status_code == 303
    assert response.body is None
    assert response.text == "approved"
    assert len(requests) == 1
    assert requests[0].headers["Authorization"] == "Bearer synthetic-token"
    assert requests[0].content == b"action=approve&note=ready+%26+checked&count=2"


def test_json_transport_encodes_and_decodes_payload() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["Content-Type"] == "application/json"
        assert json.loads(request.content) == {"handoff": "synthetic", "revision": 2}
        return httpx.Response(201, json={"receipt_id": "synthetic-receipt"})

    response = portal_transport(
        "POST",
        "http://portal.test/handoff",
        {},
        {"handoff": "synthetic", "revision": 2},
        1.0,
        http_transport=httpx.MockTransport(respond),
    )

    assert response.status_code == 201
    assert response.body == {"receipt_id": "synthetic-receipt"}


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout])
def test_transport_wraps_http_errors(error_type: type[httpx.HTTPError]) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        raise error_type("synthetic failure", request=request)

    with pytest.raises(CrossRepoSmokeError, match="Live portal transport failed") as caught:
        portal_transport(
            "GET",
            "http://portal.test/receipt",
            {},
            None,
            1.0,
            http_transport=httpx.MockTransport(respond),
        )
    assert isinstance(caught.value.__cause__, error_type)
