"""Whose request a report run is recorded for, on migrated PostgreSQL.

A signed-in user's request provisions and records that user. A signed-out
browser's user may be merged into an account, or converted into one in
place, while the simulation service is asked: the run is then recorded for
the user the check found, or not at all, never for a new user re-created
with the browser's ID. The routes run as the Public API's runtime role.
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
from policyengine_api.services.v2.identity.services import (
    convert_unauthenticated_user_in_session,
    resolve_principal_user_in_session,
)
from policyengine_api.services.v2.identity.types import (
    AccountConversionOutcome,
    UserPrincipal,
)
from tests.integration.stored_report_rows import delete_catalog, store_catalog
from tests.integration.user_report_run_support import (
    JoiningSimulationService,
    as_browser,
    client_for,
    report_body,
    stored_records,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Engine

    from tests.integration.stored_report_rows import CatalogRows

ISSUER = "https://users.example.test/"


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


def store_browser_user(engine: Engine, browser_id: UUID) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO users (id, user_type) VALUES (:id, 'unauthenticated')"),
            {"id": browser_id},
        )


def user_type(engine: Engine, user_id: UUID) -> str | None:
    with engine.begin() as connection:
        return connection.execute(
            text("SELECT user_type FROM users WHERE id = :id"), {"id": user_id}
        ).scalar_one_or_none()


def test_a_signed_in_users_request_provisions_and_records_that_user(
    owner_engine: Engine,
    catalog: CatalogRows,
    runtime_sessions: Any,
    user_ids: list[UUID],
) -> None:
    signed_in = UserPrincipal(issuer=ISSUER, subject=f"auth0|{uuid4()}")
    client = client_for(
        runtime_sessions,
        JoiningSimulationService(owner_engine, catalog),
        requester=signed_in,
    )

    response = client.post(
        "/v2/reports?country_id=us", json=report_body(catalog.policy_id)
    )

    assert response.status_code == 201, response.text
    with owner_engine.begin() as connection:
        signed_in_user_id = connection.execute(
            text(
                "SELECT user_id FROM user_identities WHERE issuer = :issuer AND "
                "subject = :subject"
            ),
            {"issuer": ISSUER, "subject": signed_in.subject},
        ).scalar_one()
    user_ids.append(signed_in_user_id)
    (record,) = stored_records(owner_engine, [signed_in_user_id])
    assert str(record.report_run_id) == response.json()["result"]["item"]["run"]["id"]
    assert user_type(owner_engine, signed_in_user_id) == "standard"


def test_a_browser_merged_while_the_service_is_asked_is_not_recorded_again(
    owner_engine: Engine,
    catalog: CatalogRows,
    runtime_sessions: Any,
    user_ids: list[UUID],
) -> None:
    browser_id = uuid4()
    store_browser_user(owner_engine, browser_id)
    account = UserPrincipal(issuer=ISSUER, subject=f"auth0|{uuid4()}")
    with runtime_sessions.begin() as session:
        account_id = resolve_principal_user_in_session(
            session, account, country_id="us"
        ).user_id
    user_ids.extend([browser_id, account_id])
    outcomes: list[AccountConversionOutcome] = []

    def sign_in_and_merge() -> None:
        with runtime_sessions.begin() as session:
            outcomes.append(
                convert_unauthenticated_user_in_session(
                    session,
                    unauthenticated_user_id=browser_id,
                    principal=account,
                    country_id="us",
                ).outcome
            )

    simulation_service = JoiningSimulationService(
        owner_engine, catalog, during_call=sign_in_and_merge
    )

    response = client_for(runtime_sessions, simulation_service).post(
        "/v2/reports?country_id=us",
        json=report_body(catalog.policy_id),
        headers=as_browser(browser_id),
    )

    assert outcomes == [AccountConversionOutcome.MERGED]
    assert response.status_code == 503, response.text
    body = response.json()
    assert body["report_id"] == str(catalog.report_ids[-1])
    assert UUID(body["report_run_id"])
    # The browser's user stays merged away, and nobody holds the record.
    assert user_type(owner_engine, browser_id) is None
    assert stored_records(owner_engine, [browser_id, account_id]) == []


def test_a_browser_converted_while_the_service_is_asked_is_recorded_as_itself(
    owner_engine: Engine,
    catalog: CatalogRows,
    runtime_sessions: Any,
    user_ids: list[UUID],
) -> None:
    browser_id = uuid4()
    store_browser_user(owner_engine, browser_id)
    user_ids.append(browser_id)
    new_account = UserPrincipal(issuer=ISSUER, subject=f"auth0|{uuid4()}")
    outcomes: list[AccountConversionOutcome] = []

    def sign_in_and_convert() -> None:
        with runtime_sessions.begin() as session:
            outcomes.append(
                convert_unauthenticated_user_in_session(
                    session,
                    unauthenticated_user_id=browser_id,
                    principal=new_account,
                    country_id="us",
                ).outcome
            )

    simulation_service = JoiningSimulationService(
        owner_engine, catalog, during_call=sign_in_and_convert
    )

    response = client_for(runtime_sessions, simulation_service).post(
        "/v2/reports?country_id=us",
        json=report_body(catalog.policy_id),
        headers=as_browser(browser_id),
    )

    assert outcomes == [AccountConversionOutcome.CONVERTED]
    assert response.status_code == 201, response.text
    (record,) = stored_records(owner_engine, [browser_id])
    assert str(record.report_run_id) == response.json()["result"]["item"]["run"]["id"]
    assert user_type(owner_engine, browser_id) == "standard"
