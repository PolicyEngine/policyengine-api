"""Economy reports against a migrated disposable Postgres database.

The service and route read the countries row as the Public API's runtime
role, so the tests prove its declared privileges cover them (rule
``api.v2.runtime-privileges-tested-as-runtime-role``). The simulation service
is a fake: these tests check what the Public API decides before asking it.
"""

from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from flask import Flask
from sqlalchemy import create_engine, text
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
from policyengine_api.services.v2.economy_reports.database_session import (
    EconomyReportDatabaseSession,
)
from policyengine_api.services.v2.economy_reports.services import (
    V2EconomyReportService,
)
from policyengine_api.services.v2.economy_reports.types import (
    EconomyReportFields,
    SimulationChoice,
)
from policyengine_api.services.v2.economy_reports.validators import (
    EconomyReportsUnsupportedError,
)
from tests.unit.v2.economy_report_support import (
    CURRENT_POLICYENGINE_VERSION,
    REPORT_ID,
    FakeEconomyReportSimulation,
    report_record,
    report_run_record,
)

# A country that has only household calculations; no real country does yet.
HOUSEHOLD_ONLY_COUNTRY_ID = "zz"
REPORT_FIELDS = EconomyReportFields(
    kind="economy",
    year=2026,
    region_code="state/ca",
    baseline=SimulationChoice(),
    reform=SimulationChoice(),
)


@pytest.fixture
def runtime_sessions(managed_v2_roles, v2_engine_as_role, disposable_v2_database_url):
    """Migrate, add the test-only household-only row, and yield runtime sessions.

    The row is removed afterwards, so later tests see only the listed
    countries.
    """
    command.upgrade(Config(str(REPO / "alembic-v2.ini")), "head")
    owner_engine = create_engine(disposable_v2_database_url, poolclass=NullPool)
    runtime_engine = v2_engine_as_role(managed_v2_roles.runtime, poolclass=NullPool)
    with owner_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO countries (id, household_enabled, society_wide_enabled) "
                "VALUES (:country_id, true, false)"
            ),
            {"country_id": HOUSEHOLD_ONLY_COUNTRY_ID},
        )
    try:
        yield sessionmaker(runtime_engine, class_=Session)
    finally:
        with owner_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM countries WHERE id = :country_id"),
                {"country_id": HOUSEHOLD_ONLY_COUNTRY_ID},
            )
        owner_engine.dispose()
        runtime_engine.dispose()


def _service(sessions, simulation) -> V2EconomyReportService:
    return V2EconomyReportService(
        EconomyReportDatabaseSession(sessions),
        simulation,
        current_policyengine_version=CURRENT_POLICYENGINE_VERSION,
    )


def test_postgres_household_only_country_is_refused_before_the_simulation_service(
    runtime_sessions,
) -> None:
    simulation = FakeEconomyReportSimulation(
        report_record(country_id=HOUSEHOLD_ONLY_COUNTRY_ID, run=report_run_record())
    )
    service = _service(runtime_sessions, simulation)

    with pytest.raises(EconomyReportsUnsupportedError) as submitted:
        service.submit_report(
            country_id=HOUSEHOLD_ONLY_COUNTRY_ID, report_input=REPORT_FIELDS
        )
    with pytest.raises(EconomyReportsUnsupportedError) as rerun:
        service.run_report(
            country_id=HOUSEHOLD_ONLY_COUNTRY_ID, report_id=REPORT_ID, force=False
        )

    for refusal in (submitted, rerun):
        assert str(refusal.value) == (
            f"Economy reports are not available for country "
            f"{HOUSEHOLD_ONLY_COUNTRY_ID!r}"
        )
    assert simulation.calls == []


def test_postgres_society_wide_country_submits_through_the_route(
    runtime_sessions,
) -> None:
    simulation = FakeEconomyReportSimulation()
    dependencies = NativeRouteDependencies(
        readiness_probe=lambda: True,
        gateway_client_factory=lambda: None,
        metadata_reader_factory=lambda: None,
        specification_provider=dict,
        v2_economy_report_service_factory=lambda: _service(
            runtime_sessions, simulation
        ),
    )
    settings = RouteImplementationSettings(
        health=RouteImplementation.FLASK_FALLBACK,
        specification=RouteImplementation.FLASK_FALLBACK,
        metadata=RouteImplementation.FLASK_FALLBACK,
    )
    client = TestClient(
        create_asgi_app(
            Flask(__name__), dependencies=dependencies, route_settings=settings
        )
    )

    response = client.post(
        "/v2/reports?country_id=us",
        json={
            "country_id": "us",
            **REPORT_FIELDS.model_dump(mode="json"),
        },
    )

    assert response.status_code == 201
    assert [name for name, _ in simulation.calls] == ["submit_report"]
