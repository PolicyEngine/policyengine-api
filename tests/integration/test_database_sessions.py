"""Tests of the tests' PostgreSQL and MySQL Session factories, and their statements.

They need the disposable v2 PostgreSQL database and, for API v1's, the
disposable MySQL database (tests/integration/conftest.py). The SQLite Session
factories are tested in tests/unit/data/test_database_sessions.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import bindparam, delete, func, select
from sqlalchemy.exc import DBAPIError
from sqlmodel import col

from policyengine_api.data.v1_sessions import unpooled_v1_sessions, v1_schema_inspector
from policyengine_api.data.v2.database import (
    unpooled_v2_read_only_sessions,
    unpooled_v2_sessions,
    v2_schema_inspector,
)
from policyengine_api.data.v2.models import (
    Country,
    Household,
    Region,
    Report,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)
from policyengine_api.data.v2.privileges import declared_privileges
from tests.fixtures.database_sessions import (
    act_as,
    act_as_owner,
    create_role,
    drop_role,
    grant,
    grant_declared_v2_privileges,
    query_plan,
    schema_inspector,
    truncate,
)
from tests.integration.simulation_rows import add_row, insert_public_api_rows

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from sqlalchemy.orm import Session, sessionmaker

    from tests.integration.conftest import ManagedV2Roles

V2_DATABASE_NAME = "policyengine_v2_alembic_test"
V1_DATABASE_NAME = "policyengine_alembic_test"


def _current_user(session: Session) -> str:
    return session.execute(select(func.current_user())).scalar_one()


def _has_table_privilege(session: Session, role: str, privilege: str) -> bool:
    return bool(
        session.execute(
            select(func.has_table_privilege(role, "public.regions", privilege))
        ).scalar_one()
    )


@pytest.fixture
def owner_session(v2_owner_sessions: sessionmaker[Session]) -> Iterator[Session]:
    """Yield an owner's Session whose writes are rolled back after the test."""
    with v2_owner_sessions() as session:
        try:
            yield session
        finally:
            session.rollback()


@pytest.fixture
def temporary_role(v2_owner_sessions: sessionmaker[Session]) -> Iterator[str]:
    """Return a role that can't log in, dropped after the test."""
    role = f"policyengine_sessions_test_{uuid4().hex[:12]}"
    with v2_owner_sessions.begin() as session:
        create_role(session, role)
    try:
        yield role
    finally:
        with v2_owner_sessions.begin() as session:
            drop_role(session, role)


def test_role_sessions_act_as_their_role_in_every_transaction(
    v2_sessions_as_role: Callable[[str], sessionmaker[Session]],
    managed_v2_roles: ManagedV2Roles,
) -> None:
    runtime_role = managed_v2_roles.runtime
    runtime_sessions = v2_sessions_as_role(runtime_role)

    with runtime_sessions.begin() as session:
        first = _current_user(session)
    with runtime_sessions.begin() as session:
        second = _current_user(session)
        countries = session.scalars(select(col(Country.id))).all()

    assert (first, second) == (runtime_role, runtime_role)
    assert countries


def test_role_sessions_hold_only_their_roles_privileges(
    v2_sessions_as_role: Callable[[str], sessionmaker[Session]],
    managed_v2_roles: ManagedV2Roles,
) -> None:
    runtime_sessions = v2_sessions_as_role(managed_v2_roles.runtime)

    with (
        runtime_sessions() as session,
        pytest.raises(DBAPIError, match="permission denied for table countries"),
    ):
        session.execute(delete(Country))


def test_act_as_lasts_until_act_as_owner_or_the_transaction_ends(
    owner_session: Session, managed_v2_roles: ManagedV2Roles
) -> None:
    runtime_role = managed_v2_roles.runtime
    owner = _current_user(owner_session)

    act_as(owner_session, runtime_role)
    acting = _current_user(owner_session)
    act_as_owner(owner_session)
    after_acting = _current_user(owner_session)
    act_as(owner_session, runtime_role)
    owner_session.rollback()
    next_transaction = _current_user(owner_session)

    assert acting == runtime_role
    assert after_acting == owner
    assert next_transaction == owner


def test_a_temporary_role_is_granted_privileges_and_dropped(
    v2_owner_sessions: sessionmaker[Session], temporary_role: str
) -> None:
    with v2_owner_sessions.begin() as session:
        before = _has_table_privilege(session, temporary_role, "SELECT")
        grant(session, "SELECT, UPDATE (label, code)", on=Region, to=temporary_role)
        after = _has_table_privilege(session, temporary_role, "SELECT")
        can_update_label = session.execute(
            select(
                func.has_column_privilege(
                    temporary_role, "public.regions", "label", "UPDATE"
                )
            )
        ).scalar_one()

    assert (before, after, can_update_label) == (False, True, True)


def test_a_dropped_role_no_longer_exists(
    v2_owner_sessions: sessionmaker[Session],
) -> None:
    role = f"policyengine_sessions_test_{uuid4().hex[:12]}"
    with v2_owner_sessions.begin() as session:
        create_role(session, role)
        grant(session, "SELECT", on=Region, to=role)
        created = session.execute(select(func.to_regrole(role))).scalar_one()
        drop_role(session, role)
        dropped = session.execute(select(func.to_regrole(role))).scalar_one()

    assert (created, dropped) == (role, None)


def test_truncate_empties_a_table_and_the_tables_referring_to_it(
    owner_session: Session,
) -> None:
    insert_public_api_rows(owner_session)

    truncate(owner_session, TaxBenefitModel)

    remaining = [
        owner_session.scalar(select(func.count()).select_from(model))
        for model in (TaxBenefitModel, TaxBenefitModelVersion)
    ]
    assert remaining == [0, 0]


def test_the_schema_inspector_reads_a_session_or_its_factory(
    owner_session: Session, v2_owner_sessions: sessionmaker[Session]
) -> None:
    tables = schema_inspector(owner_session).get_table_names(schema="public")
    from_factory = schema_inspector(v2_owner_sessions).get_table_names(schema="public")

    assert {"reports", "alembic_version"} <= set(tables)
    assert set(from_factory) == set(tables)


def test_query_plan_explains_a_statement_with_an_in_list(
    owner_session: Session,
) -> None:
    """``in_()`` sends its list as one expanding parameter, rendered at execution."""
    lookup = select(col(Report.id)).where(col(Report.id).in_([uuid4(), uuid4()]))

    plan = query_plan(owner_session, lookup)

    assert "on reports" in plan


def test_query_plan_explains_a_statement_with_a_literal_parameter(
    owner_session: Session,
) -> None:
    """A ``literal_execute`` parameter is written into the SQL when it runs."""
    lookup = select(col(Report.id)).where(
        col(Report.year) == bindparam("year", 2026, literal_execute=True)
    )

    plan = query_plan(owner_session, lookup)

    assert "on reports" in plan
    assert "2026" in plan


def test_query_plan_explains_a_statement_with_a_json_parameter(
    owner_session: Session,
) -> None:
    """A JSON parameter is sent as its JSON text, as the column's type sends it."""
    lookup = select(col(Household.id)).where(
        col(Household.household_data) == {"people": {"you": {}}}
    )

    plan = query_plan(owner_session, lookup)

    assert "on households" in plan


def test_declared_privileges_are_granted_again_without_error(
    disposable_v2_database_url: str, managed_v2_roles: ManagedV2Roles
) -> None:
    environment = managed_v2_roles.deployment_environment

    plan = grant_declared_v2_privileges(
        disposable_v2_database_url, declared_privileges(environment)
    )

    assert plan.can_apply


def test_unpooled_v2_sessions_reach_the_database_at_the_url(
    disposable_v2_database_url: str,
) -> None:
    with unpooled_v2_sessions(disposable_v2_database_url) as sessions:
        with sessions() as session:
            database = session.execute(select(func.current_database())).scalar_one()
        tables = v2_schema_inspector(sessions).get_table_names(schema="public")

    assert database == V2_DATABASE_NAME
    assert "reports" in tables


def test_unpooled_v2_read_only_sessions_refuse_writes(
    disposable_v2_database_url: str,
) -> None:
    with (
        unpooled_v2_read_only_sessions(disposable_v2_database_url) as sessions,
        sessions() as session,
    ):
        countries = session.scalars(select(col(Country.id))).all()
        with pytest.raises(DBAPIError, match="read-only transaction"):
            add_row(session, TaxBenefitModel, name=f"read-only-{uuid4().hex[:12]}")

    assert countries


def test_v1_sessions_reach_the_disposable_mysql_database(
    v1_sessions: sessionmaker[Session], disposable_v1_database_url: str
) -> None:
    with v1_sessions() as session:
        database = session.execute(select(func.database())).scalar_one()
    with unpooled_v1_sessions(disposable_v1_database_url) as sessions:
        with sessions() as session:
            unpooled_database = session.execute(select(func.database())).scalar_one()
        tables = v1_schema_inspector(sessions).get_table_names()

    assert (database, unpooled_database) == (V1_DATABASE_NAME, V1_DATABASE_NAME)
    assert "policy" in tables
