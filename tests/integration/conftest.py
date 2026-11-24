from __future__ import annotations

import os
import time
import uuid
from contextlib import ExitStack
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
import pytest

from tests.integration.deployed_api_credentials import (
    MissingServerCredentialError,
    deployed_api_client,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from sqlalchemy.orm import Session as OrmSession
    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

# The database fixtures import the tests' session factories when they run, so
# the tests of deployed services load no database code.

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


@dataclass(frozen=True)
class ManagedV2Roles:
    """The managed v2 roles in the disposable database, by what runs as them."""

    deployment_environment: str
    runtime: str
    stage12: str
    simulation_service: str
    modal_worker: str


@pytest.fixture(scope="session")
def managed_v2_roles(disposable_v2_database_url: str) -> ManagedV2Roles:
    """Create the managed v2 roles if missing and grant their declared privileges.

    The cross-database integration job does the same first with
    ``reconcile_v2_privileges.py apply --create-missing-roles``. Repeating it
    here grants nothing more there, and lets the tests run locally on their own.
    """
    from policyengine_api.data.v2.privileges import (
        MODAL_WORKER_ROLE,
        RUNTIME_ROLE,
        SIMULATION_SERVICE_ROLE,
        declared_privileges,
        stage12_role,
    )
    from tests.fixtures import database_sessions

    deployment_environment = (
        os.environ.get("DEPLOYMENT_ENVIRONMENT", "").strip() or "test"
    )
    plan = database_sessions.grant_declared_v2_privileges(
        disposable_v2_database_url, declared_privileges(deployment_environment)
    )
    if not plan.can_apply:
        pytest.fail(
            "the disposable v2 database lacks declared roles or tables: "
            f"{plan.missing_roles} {plan.missing_tables}"
        )
    return ManagedV2Roles(
        deployment_environment=deployment_environment,
        runtime=RUNTIME_ROLE,
        stage12=stage12_role(deployment_environment),
        simulation_service=SIMULATION_SERVICE_ROLE,
        modal_worker=MODAL_WORKER_ROLE,
    )


@pytest.fixture(scope="session")
def v2_owner_sessions(
    disposable_v2_database_url: str,
) -> Iterator[sessionmaker[Session]]:
    """Return Session factories of the disposable v2 database's owner (superuser)."""
    from tests.fixtures import database_sessions

    with database_sessions.v2_owner_sessions(disposable_v2_database_url) as sessions:
        yield sessions


@pytest.fixture(scope="session")
def v2_sessions_as_role(
    disposable_v2_database_url: str, managed_v2_roles: ManagedV2Roles
) -> Iterator[Callable[[str], sessionmaker[Session]]]:
    """Return a builder of Session factories whose connections act as one role.

    Every statement is checked against that role's privileges, as in staging
    and production, instead of the disposable database's owner's. The managed
    roles exist and hold their declared privileges; a test may name a role it
    created. The factories' engines are disposed of after the test session.
    """
    from tests.fixtures import database_sessions

    with ExitStack() as factories:

        def build(role: str) -> sessionmaker[Session]:
            return factories.enter_context(
                database_sessions.v2_role_sessions(disposable_v2_database_url, role)
            )

        yield build


@pytest.fixture(scope="session")
def v1_sessions(disposable_v1_database_url: str) -> Iterator[sessionmaker[OrmSession]]:
    """Return API v1's Session factories of the disposable MySQL database."""
    from tests.fixtures import database_sessions

    with database_sessions.v1_sessions(disposable_v1_database_url) as sessions:
        yield sessions


@pytest.fixture
def api_base_url() -> str:
    base_url = os.environ.get("API_BASE_URL")
    if not base_url:
        pytest.skip("API_BASE_URL is not set for deployed integration tests")
    return base_url.rstrip("/")


@pytest.fixture
def api_client(api_base_url: str):
    """Call the deployed Public API with the CI server credential on every request.

    The client is ``deployed_api_client``'s
    (``tests/integration/deployed_api_credentials.py``). The test fails, rather
    than skips, without ``CI_SERVER_ACCESS_TOKEN``.
    """
    try:
        client = deployed_api_client(api_base_url)
    except MissingServerCredentialError as error:
        pytest.fail(str(error), pytrace=False)
    with client:
        yield client


@pytest.fixture
def uncredentialed_api_client(api_base_url: str):
    """Call the deployed Public API without any credential, as an outside caller."""
    with httpx.Client(
        base_url=api_base_url,
        timeout=90.0,
        follow_redirects=True,
    ) as client:
        yield client


def _response_summary(response: httpx.Response) -> str:
    return f"HTTP {response.status_code}: {response.text[:500]}"


def _structured_error_payload(response: httpx.Response) -> dict | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    if isinstance(payload, dict) and payload.get("status") == "error":
        return payload
    return None


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
                error_payload = _structured_error_payload(response)
                if error_payload is not None:
                    return error_payload
                last_response = _response_summary(response)
            else:
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as error:
                    msg = (
                        f"{error}\n{route_name} response: {_response_summary(response)}"
                    )
                    raise httpx.HTTPStatusError(
                        msg,
                        request=error.request,
                        response=error.response,
                    ) from error
                payload = response.json()

                if payload["status"] != "computing":
                    return payload

                last_response = payload

        if time.monotonic() >= deadline:
            msg = (
                f"Timed out polling the {route_name} route; "
                f"last response was {last_response}"
            )
            raise AssertionError(msg)
        time.sleep(INTEGRATION_POLL_INTERVAL_SECONDS)


@pytest.fixture
def poll_live_endpoint():
    return _poll_live_endpoint


@pytest.fixture(scope="session")
def integration_probe_id() -> str:
    base_probe_id = os.environ.get("STAGING_API_TEST_PROBE_ID", "local-probe")
    return f"{base_probe_id}-{uuid.uuid4().hex[:8]}"
