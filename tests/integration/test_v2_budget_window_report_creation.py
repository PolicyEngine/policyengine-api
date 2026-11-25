"""Create v2 budget-window reports, then read them back from migrated PostgreSQL.

A stand-in for the simulation service's client stores the rows the
simulation service creates for a budget window (the report with its first
year's simulations, its budget-window run, and a pending report run per
year under that year's simulations) and answers with the report's and
window run's IDs. The routes run as API v1's runtime
role, checking the country and policies and reading the window back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from flask import Flask

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
from policyengine_api.services.v2.dynamics.database_session import (
    DynamicDatabaseSession,
)
from policyengine_api.services.v2.dynamics.services import V2DynamicService
from policyengine_api.services.v2.households.database_session import (
    HouseholdDatabaseSession,
)
from policyengine_api.services.v2.households.services import V2HouseholdService
from policyengine_api.services.v2.policies.database_session import (
    PolicyDatabaseSession,
)
from policyengine_api.services.v2.policies.services import V2PolicyService
from policyengine_api.services.v2.simulation_service.services import (
    SimulationSubmissionService,
)
from policyengine_api.services.v2.simulation_service.types import (
    PackageVersions,
    SubmittedBudgetWindow,
)
from policyengine_api.services.v2.stored_reports.database_session import (
    StoredReportDatabaseSession,
)
from policyengine_api.services.v2.stored_reports.services import V2StoredReportService
from tests.integration.stored_report_rows import (
    BudgetWindowYear,
    RunSettings,
    delete_catalog,
    store_budget_window_run,
    store_catalog,
    store_report,
    store_report_run,
    store_year_simulations,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

    from policyengine_api.services.v2.simulation_service.types import (
        BudgetWindowReportCreationInput,
    )
    from tests.integration.conftest import ManagedV2Roles
    from tests.integration.stored_report_rows import CatalogRows

CURRENT_VERSIONS = {"country_package_version": "1.5.0", "policyengine_version": "4.2.0"}


def current_versions(country_id: str) -> PackageVersions:
    return PackageVersions(**CURRENT_VERSIONS)


@dataclass
class StoringSimulationService:
    """Store the budget window the simulation service would create; answer its IDs."""

    owner_sessions: sessionmaker[Session]
    catalog: CatalogRows
    windows: list[BudgetWindowReportCreationInput] = field(default_factory=list)

    def submit_budget_window(
        self, report: BudgetWindowReportCreationInput
    ) -> SubmittedBudgetWindow:
        self.windows.append(report)
        with self.owner_sessions.begin() as session:
            stored = store_report(
                session,
                self.catalog,
                budget_window_size=report.budget_window_size,
                year=report.year,
            )
            pending = RunSettings(versions=CURRENT_VERSIONS, status="pending")
            window_run_id = store_budget_window_run(
                session, self.catalog, stored, pending
            )
            for year in range(report.year, report.year + report.budget_window_size):
                store_report_run(
                    session,
                    self.catalog,
                    store_year_simulations(session, self.catalog, stored, year),
                    RunSettings(
                        versions=CURRENT_VERSIONS,
                        status="pending",
                        budget_window_year=BudgetWindowYear(
                            budget_window_run_id=window_run_id, year=year
                        ),
                    ),
                )
        return SubmittedBudgetWindow(
            report_id=stored.report_id, budget_window_run_id=window_run_id
        )


@pytest.fixture
def owner_sessions(
    v2_owner_sessions: sessionmaker[Session],
) -> sessionmaker[Session]:
    command.upgrade(Config(str(REPO / "alembic-v2.ini")), "head")
    return v2_owner_sessions


@pytest.fixture
def catalog(owner_sessions: sessionmaker[Session]) -> Iterator[CatalogRows]:
    with owner_sessions.begin() as session:
        stored = store_catalog(session, "us")
    yield stored
    with owner_sessions.begin() as session:
        delete_catalog(session, stored)


@pytest.fixture
def runtime_sessions(
    managed_v2_roles: ManagedV2Roles,
    v2_sessions_as_role: Callable[[str], sessionmaker[Session]],
) -> sessionmaker[Session]:
    return v2_sessions_as_role(managed_v2_roles.runtime)


def client_for(
    sessions: Any, simulation_service: StoringSimulationService
) -> TestClient:
    """Serve the report routes as the runtime role, creating through the stand-in."""
    submissions = SimulationSubmissionService(
        countries=V2CountryService(CountryDatabaseSession(sessions)),
        households=V2HouseholdService(HouseholdDatabaseSession(sessions)),
        policies=V2PolicyService(
            PolicyDatabaseSession(sessions), running_policyengine_version="4.2.0"
        ),
        dynamics=V2DynamicService(
            DynamicDatabaseSession(sessions), running_policyengine_version="4.2.0"
        ),
        client_factory=lambda: simulation_service,
    )
    dependencies = NativeRouteDependencies(
        readiness_probe=lambda: True,
        gateway_client_factory=lambda: None,
        metadata_reader_factory=lambda: None,
        v2_stored_report_service_factory=lambda: V2StoredReportService(
            StoredReportDatabaseSession(sessions),
            current_versions=current_versions,
            submissions=submissions,
        ),
    )
    settings = RouteImplementationSettings(
        health=RouteImplementation.FLASK_FALLBACK,
        specification=RouteImplementation.FLASK_FALLBACK,
        metadata=RouteImplementation.FLASK_FALLBACK,
    )
    return TestClient(
        create_asgi_app(
            Flask(__name__), dependencies=dependencies, route_settings=settings
        )
    )


def window_body(policy_id: UUID) -> dict[str, Any]:
    return {
        "country_id": "us",
        "kind": "budget_window",
        "label": "Expanded child tax credit, three years",
        "year": 2026,
        "budget_window_size": 3,
        "region_code": "state/ca",
        "baseline": {},
        "reform": {"policy_id": str(policy_id)},
    }


def test_a_created_budget_window_is_answered_as_the_tables_hold_it(
    owner_sessions: sessionmaker[Session],
    catalog: CatalogRows,
    runtime_sessions: sessionmaker[Session],
) -> None:
    simulation_service = StoringSimulationService(owner_sessions, catalog)

    response = client_for(runtime_sessions, simulation_service).post(
        "/v2/reports?country_id=us", json=window_body(catalog.policy_id)
    )

    assert response.status_code == 201, response.text
    item = response.json()["result"]["item"]
    assert (item["id"], item["kind"]) == (str(catalog.report_ids[0]), "budget_window")
    assert (item["year"], item["budget_window_size"]) == (2026, 3)
    assert item["status"] == "pending"
    assert "trigger" not in item["run"]
    assert item["run"]["policyengine_version"] == "4.2.0"
    assert [(year["year"], year["status"]) for year in item["run"]["years"]] == [
        (2026, "pending"),
        (2027, "pending"),
        (2028, "pending"),
    ]
    assert item["result"] is None
    (sent,) = simulation_service.windows
    assert (sent.year, sent.budget_window_size) == (2026, 3)
    assert sent.reform.policy_id == catalog.policy_id


def test_a_budget_window_naming_a_policy_the_country_does_not_store_is_not_sent(
    owner_sessions: sessionmaker[Session],
    catalog: CatalogRows,
    runtime_sessions: sessionmaker[Session],
) -> None:
    simulation_service = StoringSimulationService(owner_sessions, catalog)

    response = client_for(runtime_sessions, simulation_service).post(
        "/v2/reports?country_id=us", json=window_body(uuid4())
    )

    assert response.status_code == 404
    assert simulation_service.windows == []
