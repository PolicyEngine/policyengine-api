"""Serve the v2 countries list from a migrated disposable Postgres database."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from sqlmodel import Session

from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.data.v2.settings import V2_MIGRATION_DATABASE_URL
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.migration_flags import (
    RouteImplementation,
    RouteImplementationSettings,
)
from policyengine_api.services.v2.countries.database_session import (
    CountryDatabaseSession,
)
from policyengine_api.services.v2.countries.services import V2CountryService
from tests.fixtures.v2_countries import SOCIETY_WIDE_COUNTRY_ROWS

REPO = Path(__file__).parents[2]
DISPOSABLE_DATABASE = "policyengine_v2_alembic_test"


def _disposable_url() -> str:
    database_url = os.environ.get(V2_MIGRATION_DATABASE_URL, "")
    if not database_url:
        pytest.skip(f"{V2_MIGRATION_DATABASE_URL} is not set")
    url = make_url(database_url)
    if url.database != DISPOSABLE_DATABASE or url.host not in {
        "localhost",
        "127.0.0.1",
        "::1",
        "postgres",
    }:
        pytest.fail("v2 country route tests require disposable local PostgreSQL")
    return database_url


def test_postgres_countries_list_the_rows_the_revision_inserted() -> None:
    database_url = _disposable_url()
    command.upgrade(Config(str(REPO / "alembic-v2.ini")), "head")
    engine = create_engine(database_url, poolclass=NullPool)
    sessions = sessionmaker(engine, class_=Session)
    dependencies = NativeRouteDependencies(
        readiness_probe=lambda: True,
        gateway_client_factory=lambda: None,
        metadata_reader_factory=lambda: None,
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
        engine.dispose()

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "message": None,
        "result": {"items": list(SOCIETY_WIDE_COUNTRY_ROWS)},
    }
