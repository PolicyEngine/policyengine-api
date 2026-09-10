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


@pytest.fixture(scope="session")
def disposable_v1_database_url() -> str:
    """Return a validated local MySQL URL for destructive integration tests."""

    from sqlalchemy.engine import make_url

    database_url = os.environ.get("ALEMBIC_DATABASE_URL", "")
    if not database_url:
        pytest.skip("ALEMBIC_DATABASE_URL is not set")

    url = make_url(database_url)
    if url.get_backend_name() != "mysql":
        pytest.fail("ALEMBIC_DATABASE_URL must use MySQL for this test")
    if url.host not in {"127.0.0.1", "localhost"}:
        pytest.fail("integration tests may only target local MySQL")
    if url.database != "policyengine_alembic_test":
        pytest.fail(
            "integration tests require the policyengine_alembic_test MySQL schema"
        )
    return database_url


@pytest.fixture(scope="session")
def disposable_v2_database_url() -> str:
    """Return a validated disposable PostgreSQL URL for integration tests."""

    from policyengine_api.data.v2.migration_target import (
        V2_ALEMBIC_DISPOSABLE_TEST,
        load_v2_alembic_settings,
    )
    from policyengine_api.data.v2.settings import V2_MIGRATION_DATABASE_URL

    database_url = os.environ.get(V2_MIGRATION_DATABASE_URL, "")
    if not database_url:
        pytest.skip(f"{V2_MIGRATION_DATABASE_URL} is not set")
    settings = load_v2_alembic_settings(
        {
            V2_MIGRATION_DATABASE_URL: database_url,
            V2_ALEMBIC_DISPOSABLE_TEST: os.environ.get(
                V2_ALEMBIC_DISPOSABLE_TEST,
                "",
            ),
        }
    )
    if not settings.disposable_test:
        pytest.fail("integration tests require disposable PostgreSQL mode")
    return settings.url.render_as_string(hide_password=False)


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
