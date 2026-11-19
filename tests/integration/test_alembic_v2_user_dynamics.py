"""Check the revision that adds users' saved dynamics against disposable Postgres.

The revision creates ``user_dynamics`` and changes nothing else. A saved
dynamic names a dynamic stored in its own country, which can't be deleted
while it is saved, and is deleted with its user. The downgrade drops the
table with its rows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text

from tests.fixtures.integration.alembic_v2 import alembic_v2_config, disposable_v2_url
from tests.integration.simulation_rows import (
    PublicApiRows,
    delete_public_api_rows,
    insert_public_api_rows,
    insert_row,
    refused,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Connection, Engine

DYNAMICS_REVISION = "9d1d12a7ac58"
USER_DYNAMICS_REVISION = "d417fe8b1b17"


@pytest.fixture
def engine() -> Iterator[Engine]:
    """Yield an engine on a database at head, and leave it at head."""
    command.upgrade(alembic_v2_config(), "head")
    database_engine = create_engine(disposable_v2_url())
    try:
        yield database_engine
    finally:
        command.upgrade(alembic_v2_config(), "head")
        database_engine.dispose()


@pytest.fixture
def connection(engine: Engine) -> Iterator[Connection]:
    """Yield a connection at head whose writes are rolled back after the test."""
    with engine.connect() as database_connection:
        transaction = database_connection.begin()
        try:
            yield database_connection
        finally:
            transaction.rollback()


def _schema(engine: Engine) -> dict[str, dict[str, Any]]:
    """Return each table's columns, keys, unique constraints and indexes."""
    inspector = inspect(engine)
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


def _insert_user(connection: Connection) -> object:
    user_id = uuid4()
    insert_row(
        connection,
        "users",
        id=user_id,
        user_type="standard",
        primary_country="us",
    )
    return user_id


def _insert_dynamic(
    connection: Connection, rows: PublicApiRows, *, country_id: str
) -> object:
    dynamic_id = uuid4()
    insert_row(
        connection,
        "dynamics",
        id=dynamic_id,
        country_id=country_id,
        tax_benefit_model_id=rows.model_id,
        tax_benefit_model_version_id=rows.version_id,
        canonicalization_version=1,
        content_hash=uuid4().hex * 2,
    )
    return dynamic_id


def _insert_saved_dynamic(
    connection: Connection,
    *,
    user_id: object,
    dynamic_id: object,
    country_id: str = "us",
) -> object:
    saved_dynamic_id = uuid4()
    insert_row(
        connection,
        "user_dynamics",
        id=saved_dynamic_id,
        user_id=user_id,
        dynamic_id=dynamic_id,
        country_id=country_id,
        name="CBO labour supply responses",
    )
    return saved_dynamic_id


def _saved_dynamic_count(connection: Connection, saved_dynamic_id: object) -> int:
    return int(
        connection.execute(
            text("SELECT count(*) FROM user_dynamics WHERE id = :id"),
            {"id": saved_dynamic_id},
        ).scalar_one()
    )


def test_the_revision_adds_only_the_saved_dynamics_table(engine: Engine) -> None:
    config = alembic_v2_config()
    command.downgrade(config, DYNAMICS_REVISION)
    before = _schema(engine)
    command.upgrade(config, USER_DYNAMICS_REVISION)
    after = _schema(engine)

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

    command.downgrade(config, DYNAMICS_REVISION)
    assert _schema(engine) == before
    command.upgrade(config, "head")
    command.check(config)


def test_a_saved_dynamic_names_a_dynamic_of_its_country_which_stays_while_saved(
    connection: Connection,
) -> None:
    rows = insert_public_api_rows(connection)
    user_id = _insert_user(connection)
    us_dynamic_id = _insert_dynamic(connection, rows, country_id="us")
    uk_dynamic_id = _insert_dynamic(connection, rows, country_id="uk")

    with refused(connection, match="fk_user_dynamics_dynamic_country"):
        _insert_saved_dynamic(connection, user_id=user_id, dynamic_id=uk_dynamic_id)
    with refused(connection, match="fk_user_dynamics_dynamic_country"):
        _insert_saved_dynamic(connection, user_id=user_id, dynamic_id=uuid4())
    with refused(connection, match="null value"):
        _insert_saved_dynamic(connection, user_id=user_id, dynamic_id=None)
    _insert_saved_dynamic(connection, user_id=user_id, dynamic_id=us_dynamic_id)
    _insert_saved_dynamic(
        connection, user_id=user_id, dynamic_id=uk_dynamic_id, country_id="uk"
    )
    # Saving the same dynamic again, under another name, is allowed.
    _insert_saved_dynamic(connection, user_id=user_id, dynamic_id=us_dynamic_id)

    with refused(connection, match="fk_user_dynamics_dynamic_country"):
        connection.execute(
            text("DELETE FROM dynamics WHERE id = :id"), {"id": us_dynamic_id}
        )


def test_saved_dynamics_are_deleted_with_their_user(connection: Connection) -> None:
    rows = insert_public_api_rows(connection)
    owner_id = _insert_user(connection)
    other_user_id = _insert_user(connection)
    dynamic_id = _insert_dynamic(connection, rows, country_id="us")
    owners_saved_dynamic = _insert_saved_dynamic(
        connection, user_id=owner_id, dynamic_id=dynamic_id
    )
    others_saved_dynamic = _insert_saved_dynamic(
        connection, user_id=other_user_id, dynamic_id=dynamic_id
    )

    connection.execute(text("DELETE FROM users WHERE id = :id"), {"id": owner_id})

    assert _saved_dynamic_count(connection, owners_saved_dynamic) == 0
    assert _saved_dynamic_count(connection, others_saved_dynamic) == 1


def test_the_downgrade_drops_the_saved_dynamics_with_the_table(engine: Engine) -> None:
    config = alembic_v2_config()
    command.upgrade(config, USER_DYNAMICS_REVISION)
    with engine.begin() as connection:
        rows = insert_public_api_rows(connection)
        user_id = _insert_user(connection)
        dynamic_id = _insert_dynamic(connection, rows, country_id="us")
        _insert_saved_dynamic(connection, user_id=user_id, dynamic_id=dynamic_id)
    try:
        command.downgrade(config, DYNAMICS_REVISION)
        assert "user_dynamics" not in inspect(engine).get_table_names()
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM users WHERE id = :id"), {"id": user_id}
            )
            connection.execute(
                text("DELETE FROM dynamics WHERE id = :id"), {"id": dynamic_id}
            )
            delete_public_api_rows(connection, rows)
