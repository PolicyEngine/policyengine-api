"""PostgreSQL tests of the target checks v2 Alembic runs on a persistent database.

In staging and production, ``qualify_v2_target`` runs before Alembic or the
privilege reconciliation changes anything. It reads the live database's name
and the role the statements run as, and whether that role may CREATE in
schema ``public``, and refuses a target that doesn't match the configured one.
These tests run that non-disposable path on the disposable database, as
temporary roles that don't own it, with a configured target that names the
disposable database and one of the roles.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy.engine import make_url

from policyengine_api.data.v2.migration_target import (
    ConfiguredSupabaseTarget,
    V2AlembicSettings,
    V2MigrationTargetError,
    qualify_v2_target,
)
from tests.fixtures.database_sessions import create_role, drop_role
from tests.integration.catalog_privilege_objects import SCHEMA, grant_on_schema_object

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

# A configured target's identity outside the live checks, which never read it.
TARGET_ENVIRONMENT = "persistent-path-test"
TARGET_PROJECT_REF = "abcdefghijklmnopqrst"
FRESHNESS_AUDITED_ON = date(2026, 11, 24)


@pytest.fixture
def temporary_role(
    v2_owner_sessions: sessionmaker[Session],
) -> Iterator[Callable[..., str]]:
    """Return a builder of NOLOGIN roles, with or without CREATE on ``public``.

    The roles are dropped after the test.
    """
    created_roles: list[str] = []

    def create_temporary_role(*, can_create_in_public: bool) -> str:
        role = f"policyengine_migration_target_test_{uuid4().hex[:12]}"
        with v2_owner_sessions.begin() as session:
            create_role(session, role)
            if can_create_in_public:
                grant_on_schema_object(
                    session, "CREATE", object_kind="SCHEMA", name=SCHEMA, to=role
                )
        created_roles.append(role)
        return role

    try:
        yield create_temporary_role
    finally:
        with v2_owner_sessions.begin() as session:
            for role in created_roles:
                drop_role(session, role)


def _persistent_settings(
    database_url: str, *, migration_role: str, database_name: str | None = None
) -> V2AlembicSettings:
    """Return non-disposable settings whose target names a database and role.

    The database is the one ``database_url`` names, unless ``database_name``
    names another.
    """
    url = make_url(database_url)
    if database_name is None:
        assert url.database is not None
        database_name = url.database
    return V2AlembicSettings(
        url=url,
        disposable_test=False,
        target=ConfiguredSupabaseTarget(
            environment=TARGET_ENVIRONMENT,
            project_ref=TARGET_PROJECT_REF,
            database_name=database_name,
            migration_role=migration_role,
            freshness_audited_on=FRESHNESS_AUDITED_ON,
            freshness_audit_passed=True,
        ),
    )


def _qualify_as(sessions: sessionmaker[Session], settings: V2AlembicSettings) -> None:
    with sessions() as session:
        qualify_v2_target(session, settings)


def test_the_configured_role_that_can_create_in_public_qualifies(
    disposable_v2_database_url: str,
    v2_sessions_as_role: Callable[[str], sessionmaker[Session]],
    temporary_role: Callable[..., str],
) -> None:
    role = temporary_role(can_create_in_public=True)
    settings = _persistent_settings(
        disposable_v2_database_url,
        migration_role=role,
    )

    _qualify_as(v2_sessions_as_role(role), settings)


def test_a_role_other_than_the_configured_one_is_refused(
    disposable_v2_database_url: str,
    v2_sessions_as_role: Callable[[str], sessionmaker[Session]],
    temporary_role: Callable[..., str],
) -> None:
    """Both roles may CREATE in ``public``; only the configured one may migrate."""
    configured_role = temporary_role(can_create_in_public=True)
    other_role = temporary_role(can_create_in_public=True)
    settings = _persistent_settings(
        disposable_v2_database_url,
        migration_role=configured_role,
    )

    with pytest.raises(V2MigrationTargetError, match="identity does not match"):
        _qualify_as(v2_sessions_as_role(other_role), settings)


def test_the_configured_role_without_create_in_public_is_refused(
    disposable_v2_database_url: str,
    v2_sessions_as_role: Callable[[str], sessionmaker[Session]],
    temporary_role: Callable[..., str],
) -> None:
    role = temporary_role(can_create_in_public=False)
    settings = _persistent_settings(
        disposable_v2_database_url,
        migration_role=role,
    )

    with pytest.raises(V2MigrationTargetError, match="lacks public schema CREATE"):
        _qualify_as(v2_sessions_as_role(role), settings)


def test_a_database_other_than_the_configured_one_is_refused(
    disposable_v2_database_url: str,
    v2_sessions_as_role: Callable[[str], sessionmaker[Session]],
    temporary_role: Callable[..., str],
) -> None:
    role = temporary_role(can_create_in_public=True)
    settings = _persistent_settings(
        disposable_v2_database_url,
        database_name="postgres",
        migration_role=role,
    )

    with pytest.raises(V2MigrationTargetError, match="identity does not match"):
        _qualify_as(v2_sessions_as_role(role), settings)
