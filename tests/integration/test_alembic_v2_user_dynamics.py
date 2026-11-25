"""Check the revision that adds users' saved dynamics against disposable Postgres.

The revision creates ``user_dynamics`` and changes nothing else. A saved
dynamic names a dynamic stored in its own country, which can't be deleted
while it is saved, and is deleted with its user. The downgrade drops the
table with its rows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from sqlalchemy import delete, func, select
from sqlmodel import col

from policyengine_api.data.v2.models import Dynamic, User, UserDynamic
from tests.fixtures.database_sessions import schema_inspector
from tests.fixtures.integration.alembic_v2 import alembic_v2_config
from tests.integration.simulation_rows import (
    PublicApiRows,
    add_row,
    delete_public_api_rows,
    insert_public_api_rows,
    refused,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

# The report column drops revision, this revision's parent.
PREVIOUS_REVISION = "4e30076d4b9f"
USER_DYNAMICS_REVISION = "d417fe8b1b17"


@pytest.fixture
def sessions(
    v2_owner_sessions: sessionmaker[Session],
) -> Iterator[sessionmaker[Session]]:
    """Yield the owner's Session factories on a database at head; leave it at head.

    ``v2_owner_sessions`` checks that the target is the disposable database
    before this migrates it.
    """
    command.upgrade(alembic_v2_config(), "head")
    try:
        yield v2_owner_sessions
    finally:
        command.upgrade(alembic_v2_config(), "head")


@pytest.fixture
def session(sessions: sessionmaker[Session]) -> Iterator[Session]:
    """Yield a Session at head whose writes are rolled back after the test."""
    with sessions() as database_session:
        try:
            yield database_session
        finally:
            database_session.rollback()


def _schema(sessions: sessionmaker[Session]) -> dict[str, dict[str, Any]]:
    """Return each table's columns, keys, unique constraints and indexes."""
    with sessions() as session:
        inspector = schema_inspector(session)
        return {
            table_name: {
                "columns": sorted(
                    (column["name"], str(column["type"]), column["nullable"])
                    for column in inspector.get_columns(table_name)
                ),
                "foreign_keys": sorted(
                    (
                        tuple(key["constrained_columns"]),
                        key["referred_table"],
                        tuple(key["referred_columns"]),
                        key["options"].get("ondelete"),
                    )
                    for key in inspector.get_foreign_keys(table_name)
                ),
                "unique": sorted(
                    (str(constraint["name"]), tuple(constraint["column_names"]))
                    for constraint in inspector.get_unique_constraints(table_name)
                ),
                "indexes": sorted(
                    (
                        str(index["name"]),
                        tuple(str(column) for column in index["column_names"]),
                        bool(index["unique"]),
                    )
                    for index in inspector.get_indexes(table_name)
                ),
            }
            for table_name in inspector.get_table_names()
        }


def _insert_user(session: Session) -> UUID:
    user_id = uuid4()
    add_row(session, User, id=user_id, user_type="standard", primary_country="us")
    return user_id


def _insert_dynamic(session: Session, rows: PublicApiRows, *, country_id: str) -> UUID:
    dynamic_id = uuid4()
    add_row(
        session,
        Dynamic,
        id=dynamic_id,
        country_id=country_id,
        tax_benefit_model_id=rows.model_id,
        tax_benefit_model_version_id=rows.version_id,
        canonicalization_version=1,
        content_hash=uuid4().hex * 2,
    )
    return dynamic_id


def _insert_saved_dynamic(
    session: Session,
    *,
    user_id: UUID,
    dynamic_id: UUID | None,
    country_id: str = "us",
) -> UUID:
    saved_dynamic_id = uuid4()
    add_row(
        session,
        UserDynamic,
        id=saved_dynamic_id,
        user_id=user_id,
        dynamic_id=dynamic_id,
        country_id=country_id,
        name="CBO labour supply responses",
    )
    return saved_dynamic_id


def _saved_dynamic_count(session: Session, saved_dynamic_id: UUID) -> int:
    return session.execute(
        select(func.count())
        .select_from(UserDynamic)
        .where(col(UserDynamic.id) == saved_dynamic_id)
    ).scalar_one()


def _delete_user(session: Session, user_id: UUID) -> None:
    session.execute(delete(User).where(col(User.id) == user_id))


def _delete_dynamic(session: Session, dynamic_id: UUID) -> None:
    session.execute(delete(Dynamic).where(col(Dynamic.id) == dynamic_id))


def test_the_revision_adds_only_the_saved_dynamics_table(
    sessions: sessionmaker[Session],
) -> None:
    config = alembic_v2_config()
    command.downgrade(config, PREVIOUS_REVISION)
    before = _schema(sessions)
    command.upgrade(config, USER_DYNAMICS_REVISION)
    after = _schema(sessions)

    assert "user_dynamics" not in before
    unchanged = {
        name: value for name, value in after.items() if name != "user_dynamics"
    }
    assert unchanged == before
    saved_dynamics = after["user_dynamics"]
    assert saved_dynamics["columns"] == sorted(
        [
            ("id", "UUID", False),
            ("created_at", "TIMESTAMP", False),
            ("updated_at", "TIMESTAMP", False),
            ("user_id", "UUID", False),
            ("country_id", "VARCHAR(2)", False),
            ("dynamic_id", "UUID", False),
            ("name", "VARCHAR(255)", True),
            ("description", "TEXT", True),
        ]
    )
    assert saved_dynamics["foreign_keys"] == sorted(
        [
            (("user_id",), "users", ("id",), "CASCADE"),
            (("country_id",), "countries", ("id",), "RESTRICT"),
            (
                ("dynamic_id", "country_id"),
                "dynamics",
                ("id", "country_id"),
                "RESTRICT",
            ),
        ]
    )
    assert saved_dynamics["unique"] == [
        ("uq_user_dynamics_id_country", ("id", "country_id"))
    ]
    # Postgres also lists the unique constraint's own index, checked above.
    assert {
        name for name, _columns, unique in saved_dynamics["indexes"] if not unique
    } == {
        "ix_user_dynamics_country_user_created_id",
        "ix_user_dynamics_country_dynamic",
        "ix_user_dynamics_user_id",
    }
    # The saved-policy table's columns, without its v1 reference and v3 fields.
    assert {column[0] for column in saved_dynamics["columns"]} == {
        column[0] for column in after["user_policies"]["columns"]
    } - {"policy_id", "legacy_policy_id", "baseline", "provenance"} | {"dynamic_id"}

    command.downgrade(config, PREVIOUS_REVISION)
    assert _schema(sessions) == before
    command.upgrade(config, "head")
    command.check(config)


def test_a_saved_dynamic_names_a_dynamic_of_its_country_which_stays_while_saved(
    session: Session,
) -> None:
    rows = insert_public_api_rows(session)
    user_id = _insert_user(session)
    us_dynamic_id = _insert_dynamic(session, rows, country_id="us")
    uk_dynamic_id = _insert_dynamic(session, rows, country_id="uk")

    with refused(session, match="fk_user_dynamics_dynamic_country"):
        _insert_saved_dynamic(session, user_id=user_id, dynamic_id=uk_dynamic_id)
    with refused(session, match="fk_user_dynamics_dynamic_country"):
        _insert_saved_dynamic(session, user_id=user_id, dynamic_id=uuid4())
    with refused(session, match="null value"):
        _insert_saved_dynamic(session, user_id=user_id, dynamic_id=None)
    _insert_saved_dynamic(session, user_id=user_id, dynamic_id=us_dynamic_id)
    _insert_saved_dynamic(
        session, user_id=user_id, dynamic_id=uk_dynamic_id, country_id="uk"
    )
    # Saving the same dynamic again, under another name, is allowed.
    _insert_saved_dynamic(session, user_id=user_id, dynamic_id=us_dynamic_id)

    with refused(session, match="fk_user_dynamics_dynamic_country"):
        _delete_dynamic(session, us_dynamic_id)


def test_saved_dynamics_are_deleted_with_their_user(session: Session) -> None:
    rows = insert_public_api_rows(session)
    owner_id = _insert_user(session)
    other_user_id = _insert_user(session)
    dynamic_id = _insert_dynamic(session, rows, country_id="us")
    owners_saved_dynamic = _insert_saved_dynamic(
        session, user_id=owner_id, dynamic_id=dynamic_id
    )
    others_saved_dynamic = _insert_saved_dynamic(
        session, user_id=other_user_id, dynamic_id=dynamic_id
    )

    _delete_user(session, owner_id)

    assert _saved_dynamic_count(session, owners_saved_dynamic) == 0
    assert _saved_dynamic_count(session, others_saved_dynamic) == 1


def test_the_downgrade_drops_the_saved_dynamics_with_the_table(
    sessions: sessionmaker[Session],
) -> None:
    config = alembic_v2_config()
    # Step down from head, so the downgrade below runs this revision's step alone.
    command.downgrade(config, USER_DYNAMICS_REVISION)
    with sessions.begin() as session:
        rows = insert_public_api_rows(session)
        user_id = _insert_user(session)
        dynamic_id = _insert_dynamic(session, rows, country_id="us")
        _insert_saved_dynamic(session, user_id=user_id, dynamic_id=dynamic_id)
    try:
        command.downgrade(config, PREVIOUS_REVISION)
        assert "user_dynamics" not in schema_inspector(sessions).get_table_names()
    finally:
        with sessions.begin() as session:
            _delete_user(session, user_id)
            _delete_dynamic(session, dynamic_id)
            delete_public_api_rows(session, rows)
