"""Check the user types revision against disposable Postgres.

Revision 617f531f1506 replaces the users type check with one that also allows
author and admin, and changes nothing else; its downgrade restores the check
that allows only unauthenticated and standard, so it fails while any user is
an author or an admin. Revision 970be5d29283, on it, adds user_type_changes and
changes nothing else. Revision f519a77ba122, on the SPM availability revision,
adds user_invitations and user_type_changes.dismissed_at, and lets a change's
source be invitation; its downgrade fails while any change's source is
invitation.
"""

import re
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, inspect, text

from tests.fixtures.integration.alembic_v2 import (
    alembic_v2_config,
    disposable_v2_url,
)

# The saved-item keys revision, the parent of the user types revision.
USER_TYPES_PREVIOUS_REVISION = "81b728a088e7"
USER_TYPES_REVISION = "617f531f1506"
# The user type changes revision, on the user types revision.
USER_TYPE_CHANGES_REVISION = "970be5d29283"
# The SPM availability revision, and the user invitations revision on it.
SPM_AVAILABILITY_REVISION = "0c136a278f29"
USER_INVITATIONS_REVISION = "f519a77ba122"


def _check_names(engine: Engine, table_name: str) -> set[str]:
    return {
        constraint["name"]
        for constraint in inspect(engine).get_check_constraints(table_name)
    }


def _schema_shape(engine: Engine) -> dict[str, dict[str, Any]]:
    """Reflect every table's columns and defaults, keys, indexes and checks."""
    inspector = inspect(engine)
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


def test_user_types_revision_changes_only_the_user_type_check() -> None:
    """The revision replaces the users type check and changes nothing else."""
    database_url = disposable_v2_url()
    config = alembic_v2_config()
    engine = create_engine(database_url)

    try:
        command.downgrade(config, USER_TYPES_PREVIOUS_REVISION)
        parent = _schema_shape(engine)
        command.upgrade(config, USER_TYPES_REVISION)
        revision = _schema_shape(engine)

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
        engine.dispose()


@pytest.mark.parametrize("user_type", ["author", "admin"])
def test_user_types_revision_accepts_authors_and_admins_until_downgraded(
    user_type: str,
) -> None:
    """Either type is stored, and alone keeps the downgrade from running."""
    database_url = disposable_v2_url()
    config = alembic_v2_config()
    engine = create_engine(database_url)
    user_id = uuid4()

    def insert_user(inserted_id: UUID, inserted_type: str) -> None:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, user_type, primary_country) "
                    "VALUES (:user_id, :user_type, 'us')"
                ),
                {"user_id": inserted_id, "user_type": inserted_type},
            )

    try:
        command.downgrade(config, USER_TYPES_PREVIOUS_REVISION)
        with pytest.raises(sa.exc.IntegrityError):
            insert_user(user_id, user_type)

        command.upgrade(config, USER_TYPES_REVISION)
        insert_user(user_id, user_type)
        with pytest.raises(sa.exc.IntegrityError):
            insert_user(uuid4(), "editor")
        with pytest.raises(sa.exc.IntegrityError):
            command.downgrade(config, USER_TYPES_PREVIOUS_REVISION)
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            assert context.get_current_revision() == USER_TYPES_REVISION
            stored_type = connection.execute(
                text("SELECT user_type FROM users WHERE id = :user_id"),
                {"user_id": user_id},
            ).scalar_one()
        assert stored_type == user_type
        # The refused downgrade left the revision's check in place.
        assert _check_names(engine, "users") >= {"ck_users_user_type_allowed"}
        assert "ck_users_user_type" not in _check_names(engine, "users")
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM users WHERE id = :user_id"), {"user_id": user_id}
            )
        command.downgrade(config, USER_TYPES_PREVIOUS_REVISION)
        command.upgrade(config, "head")
        engine.dispose()


def test_user_type_changes_revision_adds_only_its_table() -> None:
    """The revision adds user_type_changes, and its downgrade drops only that."""
    database_url = disposable_v2_url()
    config = alembic_v2_config()
    engine = create_engine(database_url)

    try:
        command.downgrade(config, USER_TYPES_REVISION)
        parent = _schema_shape(engine)
        command.upgrade(config, USER_TYPE_CHANGES_REVISION)
        revision = _schema_shape(engine)

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
        engine.dispose()


def test_user_invitations_revision_adds_invitations_and_dismissals_only() -> None:
    """The revision adds user_invitations, dismissed_at and a wider source check."""
    database_url = disposable_v2_url()
    config = alembic_v2_config()
    engine = create_engine(database_url)

    try:
        command.downgrade(config, SPM_AVAILABILITY_REVISION)
        parent = _schema_shape(engine)
        command.upgrade(config, USER_INVITATIONS_REVISION)
        revision = _schema_shape(engine)

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
        engine.dispose()


def test_user_invitations_revision_records_invitation_changes_until_downgraded() -> (
    None
):
    """A change from an invitation is stored, and keeps the downgrade from running."""
    database_url = disposable_v2_url()
    config = alembic_v2_config()
    engine = create_engine(database_url)
    user_id = uuid4()

    def insert_change() -> None:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO user_type_changes (id, user_id, "
                    "previous_user_type, new_user_type, source) VALUES "
                    "(:change_id, :user_id, 'standard', 'author', 'invitation')"
                ),
                {"change_id": uuid4(), "user_id": user_id},
            )

    try:
        command.downgrade(config, SPM_AVAILABILITY_REVISION)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, user_type, primary_country) "
                    "VALUES (:user_id, 'author', 'us')"
                ),
                {"user_id": user_id},
            )
        with pytest.raises(sa.exc.IntegrityError):
            insert_change()

        command.upgrade(config, USER_INVITATIONS_REVISION)
        insert_change()
        with pytest.raises(sa.exc.IntegrityError):
            command.downgrade(config, SPM_AVAILABILITY_REVISION)
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            assert context.get_current_revision() == USER_INVITATIONS_REVISION
        assert "user_invitations" in inspect(engine).get_table_names()
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM users WHERE id = :user_id"), {"user_id": user_id}
            )
        command.downgrade(config, SPM_AVAILABILITY_REVISION)
        command.upgrade(config, "head")
        engine.dispose()
