"""Check the user types revision against disposable Postgres.

Revision 617f531f1506 replaces the users type check with one that also allows
author and admin, and changes nothing else; its downgrade restores the check
that allows only unauthenticated and standard, so it fails while any user is
an author or an admin. Revision 970be5d29283, on it, adds user_type_changes and
changes nothing else. Revision f519a77ba122, on the shared reports
revision, adds user_invitations and user_type_changes.dismissed_at, and lets
a change's source be invitation; its downgrade fails while any change's
source is invitation.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from sqlalchemy import String, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column, registry
from sqlmodel import col

from policyengine_api.data.v2.models import User
from tests.fixtures.database_sessions import schema_inspector
from tests.fixtures.integration.alembic_v2 import alembic_v2_config
from tests.integration.alembic_version_rows import current_revision
from tests.integration.simulation_rows import add_row

if TYPE_CHECKING:
    from sqlalchemy.engine import Inspector
    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

# The saved-item keys revision, the parent of the user types revision.
USER_TYPES_PREVIOUS_REVISION = "81b728a088e7"
USER_TYPES_REVISION = "617f531f1506"
# The user type changes revision, on the user types revision.
USER_TYPE_CHANGES_REVISION = "970be5d29283"
# The shared reports revision, and the user invitations revision on it.
SHARED_REPORTS_REVISION = "94dc43079186"
USER_INVITATIONS_REVISION = "f519a77ba122"

shared_reports_revision_tables = registry()


@shared_reports_revision_tables.mapped
class UserTypeChangeAt94dc43079186:
    """The ``user_type_changes`` table at revision 94dc43079186.

    It has no ``dismissed_at`` until the user invitations revision on it,
    f519a77ba122, which keeps every column mapped here. ``created_at``, which
    the database fills in, isn't mapped. ``users`` has the same columns at
    every revision these tests reach, so they write it through ``User``.
    """

    __tablename__ = "user_type_changes"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID]
    changed_by_user_id: Mapped[UUID | None]
    previous_user_type: Mapped[str] = mapped_column(String(16))
    new_user_type: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(16))


def _check_names(sessions: sessionmaker[Session], table_name: str) -> set[str | None]:
    return {
        constraint["name"]
        for constraint in schema_inspector(sessions).get_check_constraints(table_name)
    }


def _schema_shape(sessions: sessionmaker[Session]) -> dict[str, dict[str, Any]]:
    """Reflect every table's columns and defaults, keys, indexes and checks."""
    with sessions() as session:
        return _reflected_shape(schema_inspector(session))


def _reflected_shape(inspector: Inspector) -> dict[str, dict[str, Any]]:
    """Describe each public table but Alembic's own, as the Inspector reads it."""
    return {
        table_name: {
            "columns": [
                (
                    column["name"],
                    str(column["type"]),
                    column["nullable"],
                    column.get("default"),
                )
                for column in inspector.get_columns(table_name)
            ],
            "primary_key": inspector.get_pk_constraint(table_name),
            "foreign_keys": sorted(
                (key["name"], key["constrained_columns"], key["referred_table"])
                for key in inspector.get_foreign_keys(table_name)
            ),
            "unique_constraints": sorted(
                (unique["name"], unique["column_names"])
                for unique in inspector.get_unique_constraints(table_name)
            ),
            "indexes": sorted(
                (index["name"], index["column_names"])
                for index in inspector.get_indexes(table_name)
            ),
            "checks": {
                check["name"]: check["sqltext"]
                for check in inspector.get_check_constraints(table_name)
            },
        }
        for table_name in inspector.get_table_names(schema="public")
        if table_name != "alembic_version"
    }


def test_user_types_revision_changes_only_the_user_type_check(
    v2_owner_sessions: sessionmaker[Session],
) -> None:
    """The revision replaces the users type check and changes nothing else."""
    config = alembic_v2_config()

    try:
        command.downgrade(config, USER_TYPES_PREVIOUS_REVISION)
        parent = _schema_shape(v2_owner_sessions)
        command.upgrade(config, USER_TYPES_REVISION)
        revision = _schema_shape(v2_owner_sessions)

        changed_tables = sorted(
            table_name
            for table_name in set(parent) | set(revision)
            if revision.get(table_name) != parent.get(table_name)
        )
        assert changed_tables == ["users"]
        parent_users = dict(parent["users"])
        revision_users = dict(revision["users"])
        parent_checks = dict(parent_users.pop("checks"))
        revision_checks = dict(revision_users.pop("checks"))
        assert revision_users == parent_users
        assert re.findall(r"'(\w+)'", parent_checks.pop("ck_users_user_type")) == [
            "unauthenticated",
            "standard",
        ]
        allowed_types = revision_checks.pop("ck_users_user_type_allowed")
        assert re.findall(r"'(\w+)'", allowed_types) == [
            "unauthenticated",
            "standard",
            "author",
            "admin",
        ]
        # The users table's other checks, conditions included, are unchanged.
        assert revision_checks == parent_checks
    finally:
        command.upgrade(config, "head")


def _delete_user(sessions: sessionmaker[Session], user_id: UUID) -> None:
    """Delete the user, and the changes of its type with it."""
    with sessions.begin() as session:
        session.execute(delete(User).where(col(User.id) == user_id))


@pytest.mark.parametrize("user_type", ["author", "admin"])
def test_user_types_revision_accepts_authors_and_admins_until_downgraded(
    v2_owner_sessions: sessionmaker[Session], user_type: str
) -> None:
    """Either type is stored, and alone keeps the downgrade from running."""
    config = alembic_v2_config()
    user_id = uuid4()

    def insert_user(inserted_id: UUID, inserted_type: str) -> None:
        with v2_owner_sessions.begin() as session:
            add_row(
                session,
                User,
                id=inserted_id,
                user_type=inserted_type,
                primary_country="us",
            )

    try:
        command.downgrade(config, USER_TYPES_PREVIOUS_REVISION)
        with pytest.raises(IntegrityError):
            insert_user(user_id, user_type)

        command.upgrade(config, USER_TYPES_REVISION)
        insert_user(user_id, user_type)
        with pytest.raises(IntegrityError):
            insert_user(uuid4(), "editor")
        with pytest.raises(IntegrityError):
            command.downgrade(config, USER_TYPES_PREVIOUS_REVISION)
        assert current_revision(v2_owner_sessions) == USER_TYPES_REVISION
        with v2_owner_sessions() as session:
            stored_type = session.scalars(
                select(col(User.user_type)).where(col(User.id) == user_id)
            ).one()
        assert stored_type == user_type
        # The refused downgrade left the revision's check in place.
        assert _check_names(v2_owner_sessions, "users") >= {
            "ck_users_user_type_allowed"
        }
        assert "ck_users_user_type" not in _check_names(v2_owner_sessions, "users")
    finally:
        _delete_user(v2_owner_sessions, user_id)
        command.downgrade(config, USER_TYPES_PREVIOUS_REVISION)
        command.upgrade(config, "head")


def test_user_type_changes_revision_adds_only_its_table(
    v2_owner_sessions: sessionmaker[Session],
) -> None:
    """The revision adds user_type_changes, and its downgrade drops only that."""
    config = alembic_v2_config()

    try:
        command.downgrade(config, USER_TYPES_REVISION)
        parent = _schema_shape(v2_owner_sessions)
        command.upgrade(config, USER_TYPE_CHANGES_REVISION)
        revision = _schema_shape(v2_owner_sessions)

        assert set(revision) - set(parent) == {"user_type_changes"}
        assert {table_name: revision[table_name] for table_name in parent} == parent
        changes = revision["user_type_changes"]
        assert {foreign_key[2] for foreign_key in changes["foreign_keys"]} == {"users"}
        assert sorted(changes["indexes"]) == [
            ("ix_user_type_changes_changed_by_user_id", ["changed_by_user_id"]),
            ("ix_user_type_changes_user_id_created_at", ["user_id", "created_at"]),
        ]
        assert set(changes["checks"]) == {
            "ck_user_type_changes_previous_user_type",
            "ck_user_type_changes_new_user_type",
            "ck_user_type_changes_changed_type",
            "ck_user_type_changes_source",
        }
    finally:
        command.upgrade(config, "head")


def test_user_invitations_revision_adds_invitations_and_dismissals_only(
    v2_owner_sessions: sessionmaker[Session],
) -> None:
    """The revision adds user_invitations, dismissed_at and a wider source check."""
    config = alembic_v2_config()

    try:
        command.downgrade(config, SHARED_REPORTS_REVISION)
        parent = _schema_shape(v2_owner_sessions)
        command.upgrade(config, USER_INVITATIONS_REVISION)
        revision = _schema_shape(v2_owner_sessions)

        assert set(revision) - set(parent) == {"user_invitations"}
        changed_tables = sorted(
            table_name
            for table_name in parent
            if revision[table_name] != parent[table_name]
        )
        assert changed_tables == ["user_type_changes"]
        parent_changes = dict(parent["user_type_changes"])
        revision_changes = dict(revision["user_type_changes"])
        parent_columns = parent_changes.pop("columns")
        revision_columns = revision_changes.pop("columns")
        assert revision_columns == [
            *parent_columns,
            ("dismissed_at", "TIMESTAMP", True, None),
        ]
        parent_checks = dict(parent_changes.pop("checks"))
        revision_checks = dict(revision_changes.pop("checks"))
        assert revision_changes == parent_changes
        assert re.findall(
            r"'(\w+)'", parent_checks.pop("ck_user_type_changes_source")
        ) == ["admin_route", "script"]
        assert re.findall(
            r"'(\w+)'", revision_checks.pop("ck_user_type_changes_source_allowed")
        ) == ["admin_route", "script", "invitation"]
        assert revision_checks == parent_checks

        invitations = revision["user_invitations"]
        assert sorted(invitations["foreign_keys"]) == [
            (
                "fk_user_invitations_accepted_by_user_id_users",
                ["accepted_by_user_id"],
                "users",
            ),
            (
                "fk_user_invitations_invited_by_user_id_users",
                ["invited_by_user_id"],
                "users",
            ),
        ]
        assert invitations["unique_constraints"] == [
            ("uq_user_invitations_token_hash", ["token_hash"])
        ]
        assert set(invitations["checks"]) == {
            "ck_user_invitations_user_type",
            "ck_user_invitations_accepted_or_revoked",
        }
    finally:
        command.upgrade(config, "head")


def test_user_invitations_revision_records_invitation_changes_until_downgraded(
    v2_owner_sessions: sessionmaker[Session],
) -> None:
    """A change from an invitation is stored, and keeps the downgrade from running."""
    config = alembic_v2_config()
    user_id = uuid4()

    def insert_change() -> None:
        with v2_owner_sessions.begin() as session:
            add_row(
                session,
                UserTypeChangeAt94dc43079186,
                id=uuid4(),
                user_id=user_id,
                previous_user_type="standard",
                new_user_type="author",
                source="invitation",
            )

    try:
        command.downgrade(config, SHARED_REPORTS_REVISION)
        with v2_owner_sessions.begin() as session:
            add_row(session, User, id=user_id, user_type="author", primary_country="us")
        with pytest.raises(IntegrityError):
            insert_change()

        command.upgrade(config, USER_INVITATIONS_REVISION)
        insert_change()
        with pytest.raises(IntegrityError):
            command.downgrade(config, SHARED_REPORTS_REVISION)
        assert current_revision(v2_owner_sessions) == USER_INVITATIONS_REVISION
        assert (
            "user_invitations" in schema_inspector(v2_owner_sessions).get_table_names()
        )
    finally:
        _delete_user(v2_owner_sessions, user_id)
        command.downgrade(config, SHARED_REPORTS_REVISION)
        command.upgrade(config, "head")
