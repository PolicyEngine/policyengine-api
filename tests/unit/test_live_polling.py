from unittest.mock import Mock

import httpx

from tests.integration import conftest as live_polling


def _response(
    status_code: int,
    *,
    json_payload: dict | None = None,
    text: str | None = None,
) -> httpx.Response:
    request = httpx.Request("GET", "https://example.test/economy")
    if json_payload is not None:
        return httpx.Response(status_code, json=json_payload, request=request)
    return httpx.Response(status_code, text=text, request=request)


def test_structured_bad_gateway_response_is_returned_immediately(monkeypatch):
    payload = {
        "status": "error",
        "message": "Simulation worker exited",
        "result": None,
    }
    client = Mock()
    client.get.return_value = _response(502, json_payload=payload)
    monkeypatch.setattr(live_polling, "INTEGRATION_TIMEOUT_SECONDS", 0)

    result = live_polling._poll_live_endpoint(
        client,
        "/us/economy/1/over/2",
        {},
        route_name="economy",
    )

    assert result == payload
    client.get.assert_called_once()


def test_unstructured_bad_gateway_response_is_retried(monkeypatch):
    success_payload = {"status": "ok", "result": {"budget": {}}}
    client = Mock()
    client.get.side_effect = [
        _response(502, text="<html>Temporary proxy failure</html>"),
        _response(200, json_payload=success_payload),
    ]
    monkeypatch.setattr(live_polling.time, "sleep", lambda _: None)

    result = live_polling._poll_live_endpoint(
        client,
        "/us/economy/1/over/2",
        {},
        route_name="economy",
    )

    assert result == success_payload
    assert client.get.call_count == 2
