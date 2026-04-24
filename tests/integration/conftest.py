import os

import httpx
import pytest


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
        timeout=30.0,
        follow_redirects=True,
    ) as client:
        yield client


@pytest.fixture
def integration_probe_id() -> str:
    return os.environ.get("STAGING_API_TEST_PROBE_ID", "local-probe")
