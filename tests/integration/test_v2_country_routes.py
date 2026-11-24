"""Serve and check the v2 countries from a migrated disposable Postgres database.

The route and the startup check run as API v1's runtime role, so the
tests prove the role's declared privileges cover them (rule
``api.v2.runtime-privileges-tested-as-runtime-role``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from flask import Flask
from sqlalchemy import delete
from sqlmodel import col

from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.constants import REPO
from policyengine_api.data.v2.models import Country
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.migration_flags import (
    RouteImplementation,
    RouteImplementationSettings,
)
from policyengine_api.services.v2.countries.database_session import (
    CountryDatabaseSession,
)
from policyengine_api.services.v2.countries.services import V2CountryService
from policyengine_api.services.v2.countries.validators import (
    CountryListMismatchError,
)
from policyengine_api.supported_countries import SUPPORTED_COUNTRY_IDS
from tests.fixtures.v2_countries import LISTED_COUNTRY_ROWS
from tests.integration.simulation_rows import add_row

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

    from tests.integration.conftest import ManagedV2Roles


def test_postgres_countries_list_the_rows_the_revision_inserted(
    managed_v2_roles: ManagedV2Roles,
    v2_sessions_as_role: Callable[[str], sessionmaker[Session]],
) -> None:
    command.upgrade(Config(str(REPO / "alembic-v2.ini")), "head")
    sessions = v2_sessions_as_role(managed_v2_roles.runtime)
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

    response = client.get("/v2/countries")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "message": None,
        "result": {"items": list(LISTED_COUNTRY_ROWS)},
    }


def test_postgres_countries_match_the_code_list_as_the_runtime_role(
    managed_v2_roles: ManagedV2Roles,
    v2_sessions_as_role: Callable[[str], sessionmaker[Session]],
    v2_owner_sessions: sessionmaker[Session],
) -> None:
    """The startup check passes on the revision's rows and fails on an extra row."""
    command.upgrade(Config(str(REPO / "alembic-v2.ini")), "head")
    service = V2CountryService(
        CountryDatabaseSession(v2_sessions_as_role(managed_v2_roles.runtime))
    )

    try:
        service.verify_countries_match_code_list(SUPPORTED_COUNTRY_IDS)

        with v2_owner_sessions.begin() as session:
            add_row(
                session,
                Country,
                id="ca",
                household_enabled=True,
                society_wide_enabled=False,
            )
        with pytest.raises(CountryListMismatchError) as raised:
            service.verify_countries_match_code_list(SUPPORTED_COUNTRY_IDS)
        assert raised.value.rows_not_listed == ("ca",)
    finally:
        with v2_owner_sessions.begin() as session:
            session.execute(delete(Country).where(col(Country.id) == "ca"))
