"""HTTP conventions shared by the Public API's clients of the simulation service."""

from __future__ import annotations

import httpx
import pytest

from policyengine_api.libs.simulation_http import (
    attach_request_identifiers,
    required_base_url,
)
from policyengine_api.observability.identifiers import OBSERVABILITY_ID_HEADER
from policyengine_api.request_context import (
    REQUEST_ID_HEADER,
    _asgi_observability_id,
    _asgi_request_id,
)

ENVIRONMENT_NAME = "SIMULATION_ENTRYPOINT_URL"
OBSERVABILITY_ID = "00000000-0000-4000-8000-000000000042"


def test_a_base_url_is_read_without_its_trailing_slash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENVIRONMENT_NAME, " https://simulation.example.test/ ")

    assert required_base_url(ENVIRONMENT_NAME) == "https://simulation.example.test"


def test_a_missing_base_url_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENVIRONMENT_NAME, raising=False)

    with pytest.raises(ValueError, match=f"{ENVIRONMENT_NAME} is required"):
        required_base_url(ENVIRONMENT_NAME)


@pytest.mark.parametrize(
    "url",
    [
        "simulation.example.test",
        "ftp://simulation.example.test",
        "https://user:secret@simulation.example.test",
        "https://simulation.example.test/?mode=test",
        "https://simulation.example.test/#part",
    ],
)
def test_an_unusable_base_url_is_refused(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv(ENVIRONMENT_NAME, url)

    with pytest.raises(ValueError, match="absolute HTTP"):
        required_base_url(ENVIRONMENT_NAME)


def test_a_request_carries_the_current_identifiers() -> None:
    request = httpx.Request("GET", "https://simulation.example.test/health")
    request_token = _asgi_request_id.set("api-request-id")
    observability_token = _asgi_observability_id.set(OBSERVABILITY_ID)
    try:
        attach_request_identifiers(request)
    finally:
        _asgi_request_id.reset(request_token)
        _asgi_observability_id.reset(observability_token)

    assert request.headers[REQUEST_ID_HEADER] == "api-request-id"
    assert request.headers[OBSERVABILITY_ID_HEADER] == OBSERVABILITY_ID


def test_a_request_outside_an_api_request_carries_no_identifiers() -> None:
    request = httpx.Request("GET", "https://simulation.example.test/health")

    attach_request_identifiers(request)

    assert REQUEST_ID_HEADER not in request.headers
    assert OBSERVABILITY_ID_HEADER not in request.headers
