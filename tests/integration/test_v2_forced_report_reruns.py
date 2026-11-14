"""Only admin users may force a report's re-run, on migrated PostgreSQL.

C1 · 24's answer: ``POST /v2/reports/{report_id}/runs`` takes ``force``
from an admin user and refuses it, before the simulation service is asked,
from anyone else: 401 without a user credential, 403 for a signed-out
browser or a user below admin. An unforced re-run needs no credential. The
routes run as the Public API's runtime role.
"""

from __future__ import annotations

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
    delete_catalog,
    store_catalog,
    store_report,
)
from tests.integration.user_report_run_support import (
    JoiningSimulationService,
    as_browser,
    client_for,
    store_signed_in_user,
    stored_records,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Engine

    from tests.integration.stored_report_rows import CatalogRows


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
def user_ids(owner_engine: Engine) -> Iterator[list[UUID]]:
    """Collect the users a test makes, and delete them and their records after."""
    collected: list[UUID] = []
    yield collected
    with owner_engine.begin() as connection:
        connection.execute(
            text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": collected}
        )


def test_a_forced_rerun_without_a_user_credential_is_refused_with_401(
    owner_engine: Engine, catalog: CatalogRows, runtime_sessions: Any
) -> None:
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog)
    simulation_service = JoiningSimulationService(owner_engine, catalog)

    response = client_for(runtime_sessions, simulation_service).post(
        f"/v2/reports/{report.report_id}/runs?country_id=us", json={"force": True}
    )

    assert response.status_code == 401, response.text
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert "admin" in response.json()["message"]
    assert simulation_service.reruns == []


@pytest.mark.parametrize("requester_type", ["unauthenticated", "standard", "author"])
def test_a_forced_rerun_by_anyone_below_admin_is_refused_with_403(
    owner_engine: Engine,
    catalog: CatalogRows,
    runtime_sessions: Any,
    user_ids: list[UUID],
    requester_type: str,
) -> None:
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog)
    simulation_service = JoiningSimulationService(owner_engine, catalog)
    if requester_type == "unauthenticated":
        browser_id = uuid4()
        user_ids.append(browser_id)
        client = client_for(runtime_sessions, simulation_service)
        headers = as_browser(browser_id)
    else:
        principal, user_id = store_signed_in_user(
            runtime_sessions, owner_engine, user_type=requester_type
        )
        user_ids.append(user_id)
        client = client_for(runtime_sessions, simulation_service, requester=principal)
        headers = {}

    response = client.post(
        f"/v2/reports/{report.report_id}/runs?country_id=us",
        json={"force": True},
        headers=headers,
    )

    assert response.status_code == 403, response.text
    assert "admin" in response.json()["message"]
    assert simulation_service.reruns == []
    assert stored_records(owner_engine, user_ids) == []


def test_an_admins_forced_rerun_is_sent_and_recorded(
    owner_engine: Engine,
    catalog: CatalogRows,
    runtime_sessions: Any,
    user_ids: list[UUID],
) -> None:
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog)
    admin, admin_id = store_signed_in_user(
        runtime_sessions, owner_engine, user_type="admin"
    )
    user_ids.append(admin_id)
    simulation_service = JoiningSimulationService(owner_engine, catalog)

    response = client_for(runtime_sessions, simulation_service, requester=admin).post(
        f"/v2/reports/{report.report_id}/runs?country_id=us", json={"force": True}
    )

    assert response.status_code == 201, response.text
    (rerun,) = simulation_service.reruns
    assert rerun.force is True
    (record,) = stored_records(owner_engine, [admin_id])
    assert str(record.report_run_id) == response.json()["result"]["item"]["run"]["id"]
    assert record.trigger == "manual"
