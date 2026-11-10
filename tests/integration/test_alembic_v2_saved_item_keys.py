"""Check the saved-item keys revision against disposable Postgres.

The revision makes ``user_report_associations.report_id`` and
``user_simulation_associations.simulation_id`` foreign keys to ``reports`` and
``simulations``, both ``RESTRICT``: a saved report or simulation can't name a
row that doesn't exist, and a report or simulation a saved item names can't be
deleted. A saved item that names only its v1 report or simulation is
unaffected. The downgrade drops both keys and nothing else.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from tests.fixtures.integration.alembic_v2 import alembic_v2_config, disposable_v2_url
from tests.integration.simulation_rows import (
    PublicApiRows,
    insert_public_api_rows,
    insert_row,
    refused,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Connection, Engine

SAVED_ITEM_KEYS_PREVIOUS_REVISION = "1356f658347d"
SAVED_ITEM_KEYS_REVISION = "81b728a088e7"
SAVED_ITEM_KEYS = {
    "user_report_associations": (
        "fk_user_report_associations_report_id_reports",
        "report_id",
        "reports",
    ),
    "user_simulation_associations": (
        "fk_user_simulation_associations_simulation_id_simulations",
        "simulation_id",
        "simulations",
    ),
}


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
    command.upgrade(alembic_v2_config(), "head")
    with engine.connect() as database_connection:
        transaction = database_connection.begin()
        try:
            yield database_connection
        finally:
            transaction.rollback()


def _saved_item_keys(
    engine: Engine,
) -> dict[str, tuple[str | None, list[str], str, str | None]]:
    """Return each association table's keys to ``reports`` or ``simulations``."""
    inspector = inspect(engine)
    return {
        table_name: (
            key["name"],
            key["constrained_columns"],
            key["referred_table"],
            key["options"].get("ondelete"),
        )
        for table_name in SAVED_ITEM_KEYS
        for key in inspector.get_foreign_keys(table_name)
        if key["referred_table"] in {"reports", "simulations"}
    }


def _insert_user(connection: Connection) -> object:
    """Store a standard user, which needs a primary country."""
    user_id = uuid4()
    insert_row(connection, "users", id=user_id, primary_country="us")
    return user_id


def _insert_simulation(connection: Connection, rows: PublicApiRows) -> object:
    simulation_id = uuid4()
    insert_row(
        connection,
        "simulations",
        id=simulation_id,
        simulation_type="economy",
        dataset_id=rows.dataset_id,
        tax_benefit_model_version_id=rows.version_id,
        year=2026,
    )
    return simulation_id


def _insert_report(connection: Connection, rows: PublicApiRows) -> object:
    report_id = uuid4()
    insert_row(
        connection,
        "reports",
        id=report_id,
        label="Saved report",
        country="us",
        tax_benefit_model_id=rows.model_id,
        inputs="{}",
    )
    return report_id


def _save(
    connection: Connection, table_name: str, user_id: object, **reference: object
) -> None:
    insert_row(
        connection,
        table_name,
        id=uuid4(),
        user_id=user_id,
        country_id="us",
        **reference,
    )


def test_a_saved_item_must_name_a_stored_report_or_simulation(
    connection: Connection,
) -> None:
    rows = insert_public_api_rows(connection)
    user_id = _insert_user(connection)
    report_id = _insert_report(connection, rows)
    simulation_id = _insert_simulation(connection, rows)

    with refused(connection, IntegrityError, match="fk_user_report_associations"):
        _save(connection, "user_report_associations", user_id, report_id=uuid4())
    with refused(connection, IntegrityError, match="fk_user_simulation_associations"):
        _save(
            connection, "user_simulation_associations", user_id, simulation_id=uuid4()
        )

    _save(connection, "user_report_associations", user_id, report_id=report_id)
    _save(
        connection, "user_simulation_associations", user_id, simulation_id=simulation_id
    )
    # A saved item that names only its v1 report or simulation is unaffected.
    _save(connection, "user_report_associations", user_id, legacy_report_id=42)
    _save(connection, "user_simulation_associations", user_id, legacy_simulation_id=42)


def test_a_report_or_simulation_a_saved_item_names_cannot_be_deleted(
    connection: Connection,
) -> None:
    rows = insert_public_api_rows(connection)
    user_id = _insert_user(connection)
    report_id = _insert_report(connection, rows)
    simulation_id = _insert_simulation(connection, rows)
    _save(connection, "user_report_associations", user_id, report_id=report_id)
    _save(
        connection, "user_simulation_associations", user_id, simulation_id=simulation_id
    )

    with refused(connection, IntegrityError, match="fk_user_report_associations"):
        connection.execute(
            text("DELETE FROM reports WHERE id = :id"), {"id": report_id}
        )
    with refused(connection, IntegrityError, match="fk_user_simulation_associations"):
        connection.execute(
            text("DELETE FROM simulations WHERE id = :id"), {"id": simulation_id}
        )


def test_the_revision_adds_the_keys_and_drops_them_on_downgrade(
    engine: Engine,
) -> None:
    config = alembic_v2_config()
    command.downgrade(config, SAVED_ITEM_KEYS_PREVIOUS_REVISION)
    command.upgrade(config, SAVED_ITEM_KEYS_REVISION)
    assert _saved_item_keys(engine) == {
        table_name: (key_name, [column_name], referred_table, "RESTRICT")
        for table_name, (
            key_name,
            column_name,
            referred_table,
        ) in SAVED_ITEM_KEYS.items()
    }

    command.downgrade(config, SAVED_ITEM_KEYS_PREVIOUS_REVISION)
    assert _saved_item_keys(engine) == {}

    command.upgrade(config, SAVED_ITEM_KEYS_REVISION)
    assert set(_saved_item_keys(engine)) == set(SAVED_ITEM_KEYS)
    command.upgrade(config, "head")
    command.check(config)


def _current_revision(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(
            connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        )


@pytest.mark.parametrize(
    ("table_name", "reference"),
    [
        ("user_report_associations", {"report_id": uuid4()}),
        ("user_simulation_associations", {"simulation_id": uuid4()}),
    ],
)
def test_the_upgrade_fails_changing_nothing_while_a_saved_item_names_a_missing_row(
    engine: Engine, table_name: str, reference: dict[str, object]
) -> None:
    """Adding a key checks every existing row, so the upgrade fails and stays put.

    Before the revision a saved item could name a report or simulation that
    doesn't exist; while one does, the upgrade fails inside its transaction,
    leaving the database at the parent revision with no new key.
    """
    config = alembic_v2_config()
    command.downgrade(config, SAVED_ITEM_KEYS_PREVIOUS_REVISION)
    saved_item_id = uuid4()
    with engine.begin() as connection:
        user_id = _insert_user(connection)
        insert_row(
            connection,
            table_name,
            id=saved_item_id,
            user_id=user_id,
            country_id="us",
            **reference,
        )
    try:
        with pytest.raises(IntegrityError, match=SAVED_ITEM_KEYS[table_name][0]):
            command.upgrade(config, SAVED_ITEM_KEYS_REVISION)
        assert _current_revision(engine) == SAVED_ITEM_KEYS_PREVIOUS_REVISION
        assert _saved_item_keys(engine) == {}
    finally:
        with engine.begin() as connection:
            connection.execute(
                text(f"DELETE FROM {table_name} WHERE id = :id"), {"id": saved_item_id}
            )
            connection.execute(
                text("DELETE FROM users WHERE id = :id"), {"id": user_id}
            )
