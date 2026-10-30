"""Household reports against a migrated disposable Postgres database.

The services read the countries row, the stored household and the catalog
version as the Public API's runtime role, so the tests prove its declared
privileges cover them (rule ``api.v2.runtime-privileges-tested-as-runtime-role``).
The simulation service is a fake: these tests check what the Public API
decides and reads around it.
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
from policyengine_api.services.v2.household_reports.database_session import (
    HouseholdReportDatabaseSession,
)
from policyengine_api.services.v2.household_reports.services import (
    V2HouseholdReportService,
)
from policyengine_api.services.v2.households.database_session import (
    HouseholdDatabaseSession,
)
from policyengine_api.services.v2.households.services import V2HouseholdService
from policyengine_api.services.v2.households.types import (
    NativeHouseholdCreationInput,
)
from policyengine_api.services.v2.policies.database_session import (
    PolicyDatabaseSession,
)
from policyengine_api.services.v2.policies.services import V2PolicyService
from tests.unit.v2.economy_report_support import (
    CURRENT_POLICYENGINE_VERSION,
    FakeEconomyReportSimulation,
)
from tests.unit.v2.household_report_support import (
    HOUSEHOLD_CATALOG_VERSION_ID,
    FakeHouseholdReportSimulation,
)

# A model name no catalog publication uses, so the test rows never collide.
TEST_MODEL_NAME = "household-report-test"
# One adult in each of the US groups, in the v2 household form.
HOUSEHOLD_MEMBERSHIPS = {
    "household": "household-1",
    "family": "family-1",
    "tax_unit": "tax-unit-1",
    "spm_unit": "spm-unit-1",
    "marital_unit": "marital-unit-1",
}
HOUSEHOLD_DATA = {
    "people": [
        {
            "id": "person-1",
            "values": {"age": {"2026": 40}},
            "memberships": HOUSEHOLD_MEMBERSHIPS,
        }
    ],
    **{
        collection: [{"id": identifier, "values": {}}]
        for collection, identifier in HOUSEHOLD_MEMBERSHIPS.items()
    },
}


@pytest.fixture
def runtime_sessions(managed_v2_roles, v2_engine_as_role, disposable_v2_database_url):
    """Migrate, make the US household-only, add a catalog version, and yield sessions.

    The sessions act as the runtime role. The US row and the test catalog
    version are restored and removed afterwards, and so is any household a
    test stored: later tests in the same database count households.
    """
    command.upgrade(Config(str(REPO / "alembic-v2.ini")), "head")
    owner_engine = create_engine(disposable_v2_database_url, poolclass=NullPool)
    runtime_engine = v2_engine_as_role(managed_v2_roles.runtime, poolclass=NullPool)
    with owner_engine.begin() as connection:
        households_before = set(
            connection.execute(text("SELECT id FROM households")).scalars()
        )
        connection.execute(
            text("UPDATE countries SET society_wide_enabled = false WHERE id = 'us'")
        )
        model_id = connection.execute(
            text(
                "INSERT INTO tax_benefit_models (id, name, created_at) "
                "VALUES (gen_random_uuid(), :name, now()) RETURNING id"
            ),
            {"name": TEST_MODEL_NAME},
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO tax_benefit_model_versions "
                "(id, model_id, version, current_law_id, metadata_time_periods, "
                "created_at) VALUES (:id, :model_id, :version, 1, '[2026]', now())"
            ),
            {
                "id": HOUSEHOLD_CATALOG_VERSION_ID,
                "model_id": model_id,
                "version": CURRENT_POLICYENGINE_VERSION,
            },
        )
    try:
        yield sessionmaker(runtime_engine, class_=Session)
    finally:
        # Each step in its own transaction: a failed household removal must
        # not undo restoring the US row and removing the catalog version.
        with owner_engine.begin() as connection:
            connection.execute(
                text("UPDATE countries SET society_wide_enabled = true WHERE id = 'us'")
            )
            connection.execute(
                text("DELETE FROM tax_benefit_models WHERE name = :name"),
                {"name": TEST_MODEL_NAME},
            )
        with owner_engine.begin() as connection:
            stored_by_the_test = (
                set(connection.execute(text("SELECT id FROM households")).scalars())
                - households_before
            )
            if stored_by_the_test:
                connection.execute(
                    text("DELETE FROM households WHERE id = ANY(:household_ids)"),
                    {"household_ids": list(stored_by_the_test)},
                )
        # Read after the removal committed, as a later test would.
        with owner_engine.connect() as connection:
            households_after = set(
                connection.execute(text("SELECT id FROM households")).scalars()
            )
        owner_engine.dispose()
        runtime_engine.dispose()
    assert households_after == households_before, "the test left households behind"


def _client(sessions, simulation: FakeHouseholdReportSimulation) -> TestClient:
    households = V2HouseholdService(HouseholdDatabaseSession(sessions))
    dependencies = NativeRouteDependencies(
        readiness_probe=lambda: True,
        gateway_client_factory=lambda: None,
        metadata_reader_factory=lambda: None,
        specification_provider=dict,
        v2_economy_report_service_factory=lambda: V2EconomyReportService(
            EconomyReportDatabaseSession(sessions),
            FakeEconomyReportSimulation(),
            current_policyengine_version=CURRENT_POLICYENGINE_VERSION,
        ),
        v2_household_report_service_factory=lambda: V2HouseholdReportService(
            HouseholdReportDatabaseSession(sessions),
            households=households,
            policies=V2PolicyService(
                PolicyDatabaseSession(sessions),
                running_policyengine_version=CURRENT_POLICYENGINE_VERSION,
            ),
            simulation=simulation,
            current_policyengine_version=CURRENT_POLICYENGINE_VERSION,
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


def test_postgres_household_only_country_runs_household_reports_as_the_runtime_role(
    runtime_sessions,
) -> None:
    household = (
        V2HouseholdService(HouseholdDatabaseSession(runtime_sessions))
        .create_household(
            NativeHouseholdCreationInput(
                country_id="us", default_year=2026, household_data=HOUSEHOLD_DATA
            )
        )
        .item
    )
    simulation = FakeHouseholdReportSimulation()
    client = _client(runtime_sessions, simulation)

    submitted = client.post(
        "/v2/reports?country_id=us",
        json={
            "country_id": "us",
            "kind": "household",
            "household_id": str(household.id),
            "baseline": {},
        },
    )
    assert submitted.status_code == 201, submitted.text
    report_id = submitted.json()["result"]["item"]["id"]
    read = client.get(f"/v2/reports/{report_id}?country_id=us")
    rerun = client.post(f"/v2/reports/{report_id}/runs?country_id=us", json={})

    assert read.status_code == 200, read.text
    assert rerun.status_code == 201, rerun.text
    assert read.json()["result"]["item"]["run"]["policyengine_version"] == (
        CURRENT_POLICYENGINE_VERSION
    )
    assert rerun.json()["result"]["item"]["kind"] == "household"
    assert [name for name, _argument in simulation.calls] == [
        "submit_report",
        "get_report",
        "get_report",
        "run_report",
    ]


def test_postgres_household_only_country_still_refuses_economy_reports(
    runtime_sessions,
) -> None:
    response = _client(runtime_sessions, FakeHouseholdReportSimulation()).post(
        "/v2/reports?country_id=us",
        json={
            "country_id": "us",
            "kind": "economy",
            "year": 2026,
            "region_code": "state/ca",
            "baseline": {},
            "reform": {},
        },
    )

    assert response.status_code == 422, response.text
    assert response.json()["message"] == (
        "Economy reports are not available for country 'us'"
    )
