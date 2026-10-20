import os
import time
import uuid
from dataclasses import dataclass

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


@dataclass(frozen=True)
class ManagedV2Roles:
    """The managed v2 roles in the disposable database, by what runs as them."""

    deployment_environment: str
    runtime: str
    stage12: str


@pytest.fixture(scope="session")
def managed_v2_roles(disposable_v2_database_url: str) -> ManagedV2Roles:
    """Create the managed v2 roles if missing and grant their declared privileges.

    The cross-database integration job does the same first with
    ``reconcile_v2_privileges.py apply --create-missing-roles``. Repeating it
    here grants nothing more there, and lets the tests run locally on their own.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    from policyengine_api.data.v2.privilege_reconciliation import (
        apply_declared_privileges,
        create_missing_roles,
    )
    from policyengine_api.data.v2.privileges import (
        RUNTIME_ROLE,
        declared_privileges,
        stage12_role,
    )

    deployment_environment = (
        os.environ.get("DEPLOYMENT_ENVIRONMENT", "").strip() or "test"
    )
    declared = declared_privileges(deployment_environment)
    engine = create_engine(disposable_v2_database_url, poolclass=NullPool)
    try:
        with engine.begin() as connection:
            create_missing_roles(connection, declared)
            plan, _default_privileges = apply_declared_privileges(connection, declared)
    finally:
        engine.dispose()
    if not plan.can_apply:
        pytest.fail(
            "the disposable v2 database lacks declared roles or tables: "
            f"{plan.missing_roles} {plan.missing_tables}"
        )
    return ManagedV2Roles(
        deployment_environment=deployment_environment,
        runtime=RUNTIME_ROLE,
        stage12=stage12_role(deployment_environment),
    )


@pytest.fixture(scope="session")
def v2_engine_as_role(disposable_v2_database_url: str, managed_v2_roles):
    """Return a builder of engines whose connections act as one managed role.

    Each new connection runs ``SET ROLE`` and commits it, so every statement on
    it is checked against that role's privileges, as in staging and production,
    instead of the disposable database's superuser.
    """
    from psycopg import sql
    from sqlalchemy import create_engine, event

    def build(role: str, **engine_options):
        set_role = sql.SQL("SET ROLE {}").format(sql.Identifier(role))
        engine = create_engine(disposable_v2_database_url, **engine_options)

        @event.listens_for(engine, "connect")
        def act_as_role(dbapi_connection, _connection_record) -> None:
            with dbapi_connection.cursor() as cursor:
                cursor.execute(set_role)
            dbapi_connection.commit()

        return engine

    return build


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
