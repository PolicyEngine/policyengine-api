import os
import time
import uuid

import httpx
import pytest

INTEGRATION_TIMEOUT_SECONDS = float(
    os.environ.get("STAGING_API_TEST_TIMEOUT_SECONDS", "900")
)
INTEGRATION_POLL_INTERVAL_SECONDS = float(
    os.environ.get("STAGING_API_TEST_POLL_INTERVAL_SECONDS", "5")
)
TRANSIENT_POLL_STATUS_CODES = {500, 502, 503, 504}


@pytest.fixture
def api_base_url() -> str:
    base_url = os.environ.get("API_BASE_URL")
    if not base_url:
        pytest.skip("API_BASE_URL is not set for deployed integration tests")
    return base_url.rstrip("/")


@pytest.fixture
def api_client(api_base_url: str):
    with httpx.Client(
        base_url=api_base_url,
        timeout=90.0,
        follow_redirects=True,
    ) as client:
        yield client


def _response_summary(response: httpx.Response) -> str:
    return f"HTTP {response.status_code}: {response.text[:500]}"


def _poll_live_endpoint(
    api_client: httpx.Client,
    path: str,
    params: dict,
    *,
    route_name: str,
) -> dict:
    deadline = time.monotonic() + INTEGRATION_TIMEOUT_SECONDS
    last_response = None

    while True:
        try:
            response = api_client.get(path, params=params)
        except httpx.RequestError as error:
            last_response = f"{type(error).__name__}: {error}"
        else:
            if response.status_code in TRANSIENT_POLL_STATUS_CODES:
                last_response = _response_summary(response)
            else:
                response.raise_for_status()
                payload = response.json()

                if payload["status"] != "computing":
                    return payload

                last_response = payload

        if time.monotonic() >= deadline:
            raise AssertionError(
                f"Timed out polling the {route_name} route; "
                f"last response was {last_response}"
            )
        time.sleep(INTEGRATION_POLL_INTERVAL_SECONDS)


@pytest.fixture
def poll_live_endpoint():
    return _poll_live_endpoint


@pytest.fixture(scope="session")
def integration_probe_id() -> str:
    base_probe_id = os.environ.get("STAGING_API_TEST_PROBE_ID", "local-probe")
    return f"{base_probe_id}-{uuid.uuid4().hex[:8]}"
