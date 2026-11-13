"""Record users' requests for budget-window runs, on migrated PostgreSQL.

A budget window's run is a budget-window run with a report run per year; a
request for one records each year's report run for the user, with one
``requested_at``. The routes run as the Public API's runtime role, through
a stand-in for the simulation service that answers a window run it names or
one it stores.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from sqlmodel import Session

from policyengine_api.constants import REPO
from tests.integration.stored_report_rows import (
    STARTED_AT,
    RunSettings,
    delete_catalog,
    store_catalog,
)
from tests.integration.user_report_run_support import (
    CURRENT_VERSIONS,
    JoinedRun,
    JoiningSimulationService,
    as_browser,
    client_for,
    store_window,
    stored_records,
    window_body,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Engine

    from tests.integration.stored_report_rows import CatalogRows

WINDOW_YEARS = (2026, 2027, 2028)


@pytest.fixture
def owner_engine(disposable_v2_database_url: str) -> Iterator[Engine]:
    command.upgrade(Config(str(REPO / "alembic-v2.ini")), "head")
    engine = create_engine(disposable_v2_database_url, poolclass=NullPool)
    yield engine
    engine.dispose()


@pytest.fixture
def catalog(owner_engine: Engine) -> Iterator[CatalogRows]:
    with owner_engine.begin() as connection:
        stored = store_catalog(connection, "us")
    yield stored
    with owner_engine.begin() as connection:
        delete_catalog(connection, stored)


@pytest.fixture
def runtime_sessions(managed_v2_roles, v2_engine_as_role) -> Iterator[Any]:
    engine = v2_engine_as_role(managed_v2_roles.runtime, poolclass=NullPool)
    yield sessionmaker(engine, class_=Session)
    engine.dispose()


@pytest.fixture
def browser_id(owner_engine: Engine) -> Iterator[UUID]:
    """Name a signed-out browser, and delete its user and records after."""
    browser = uuid4()
    yield browser
    with owner_engine.begin() as connection:
        connection.execute(text("DELETE FROM users WHERE id = :id"), {"id": browser})


def window_run_years(engine: Engine, window_run_id: UUID) -> set[UUID]:
    with engine.begin() as connection:
        return set(
            connection.execute(
                text("SELECT id FROM report_runs WHERE budget_window_run_id = :id"),
                {"id": window_run_id},
            ).scalars()
        )


def test_a_budget_window_create_records_each_years_report_run(
    owner_engine: Engine,
    catalog: CatalogRows,
    runtime_sessions: Any,
    browser_id: UUID,
) -> None:
    client = client_for(
        runtime_sessions, JoiningSimulationService(owner_engine, catalog)
    )

    response = client.post(
        "/v2/reports?country_id=us",
        json=window_body(catalog.policy_id, years=len(WINDOW_YEARS)),
        headers=as_browser(browser_id),
    )

    assert response.status_code == 201, response.text
    window_run_id = UUID(response.json()["result"]["item"]["run"]["id"])
    records = stored_records(owner_engine, [browser_id])
    assert {record.report_run_id for record in records} == window_run_years(
        owner_engine, window_run_id
    )
    assert len(records) == len(WINDOW_YEARS)
    assert {record.trigger for record in records} == {"initial"}
    assert len({record.requested_at for record in records}) == 1


def test_a_budget_window_rerun_records_each_year_of_the_window_run_it_joined(
    owner_engine: Engine,
    catalog: CatalogRows,
    runtime_sessions: Any,
    browser_id: UUID,
) -> None:
    with owner_engine.begin() as connection:
        joined = store_window(
            connection,
            catalog,
            years=WINDOW_YEARS,
            settings=RunSettings(versions=CURRENT_VERSIONS, status="running"),
        )
        newer = store_window(
            connection,
            catalog,
            years=WINDOW_YEARS,
            settings=RunSettings(
                versions={**CURRENT_VERSIONS, "policyengine_version": "4.3.0"},
                status="pending",
                created_at=STARTED_AT + timedelta(days=1),
            ),
            report=joined.report,
        )
    simulation_service = JoiningSimulationService(
        owner_engine,
        catalog,
        joined_run=JoinedRun(
            report_id=joined.report.report_id,
            report_run_id=joined.year_run_ids[0],
            budget_window_run_id=joined.window_run_id,
        ),
    )

    response = client_for(runtime_sessions, simulation_service).post(
        f"/v2/reports/{joined.report.report_id}/runs?country_id=us",
        json={},
        headers=as_browser(browser_id),
    )

    assert response.status_code == 201, response.text
    assert response.json()["result"]["item"]["run"]["id"] == str(joined.window_run_id)
    records = stored_records(owner_engine, [browser_id])
    assert {record.report_run_id for record in records} == set(joined.year_run_ids)
    assert not {record.report_run_id for record in records} & set(newer.year_run_ids)
    assert {record.trigger for record in records} == {"manual"}
