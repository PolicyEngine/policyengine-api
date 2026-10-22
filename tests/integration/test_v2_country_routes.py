"""Serve the v2 countries list from a migrated disposable Postgres database.

The route runs as the Public API's runtime role, so the test proves the role's
declared privileges cover it (rule
``api.v2.runtime-privileges-tested-as-runtime-role``).
"""

from __future__ import annotations

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from flask import Flask
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from sqlmodel import Session

from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.constants import REPO
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.migration_flags import (
    RouteImplementation,
    RouteImplementationSettings,
)
from policyengine_api.services.v2.countries.database_session import (
    CountryDatabaseSession,
)
from policyengine_api.services.v2.countries.services import V2CountryService
from tests.fixtures.v2_countries import LISTED_COUNTRY_ROWS


def test_postgres_countries_list_the_rows_the_revision_inserted(
    managed_v2_roles,
    v2_engine_as_role,
) -> None:
    command.upgrade(Config(str(REPO / "alembic-v2.ini")), "head")
    runtime_engine = v2_engine_as_role(managed_v2_roles.runtime, poolclass=NullPool)
    sessions = sessionmaker(runtime_engine, class_=Session)
    dependencies = NativeRouteDependencies(
        readiness_probe=lambda: True,
        gateway_client_factory=lambda: None,
        metadata_reader_factory=lambda: None,
        specification_provider=dict,
        v2_country_service_factory=lambda: V2CountryService(
            CountryDatabaseSession(sessions)
        ),
    )
    settings = RouteImplementationSettings(
        health=RouteImplementation.FLASK_FALLBACK,
        specification=RouteImplementation.FLASK_FALLBACK,
        metadata=RouteImplementation.FLASK_FALLBACK,
    )
    client = TestClient(
        create_asgi_app(
            Flask(__name__),
            dependencies=dependencies,
            route_settings=settings,
        )
    )

    try:
        response = client.get("/v2/countries")
    finally:
        runtime_engine.dispose()

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "message": None,
        "result": {"items": list(LISTED_COUNTRY_ROWS)},
    }
