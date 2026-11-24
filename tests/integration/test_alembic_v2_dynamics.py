"""Check the revision that stores dynamics like policies against disposable Postgres.

The revision gives ``dynamics`` policies' columns and drops ``name`` and
``description``, adds a partial unique index on a dynamic's values, and adds
``legacy_policy_mappings.dynamic_id``, a key to a dynamic of the mapping's
country. Nothing else changes. Its new required columns have no default, so
the upgrade fails while ``dynamics`` has a row, and the downgrade, which adds
``name`` back as required, fails the same way.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

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

PREVIOUS_REVISION = "f519a77ba122"
DYNAMICS_REVISION = "9d1d12a7ac58"
CHANGED_TABLES = frozenset({"dynamics", "legacy_policy_mappings", "parameter_values"})


@pytest.fixture
def engine() -> Iterator[Engine]:
    """Yield an engine on a database at head, and leave it at head."""
    # Check that the target is the disposable database before migrating it.
    database_url = disposable_v2_url()
    command.upgrade(alembic_v2_config(), "head")
    database_engine = create_engine(database_url)
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
    """Return each table's columns, keys, checks and indexes, comparably."""
    inspector = inspect(engine)
    return {
        table_name: {
            "columns": sorted(
                (column["name"], str(column["type"]), column["nullable"])
                for column in inspector.get_columns(table_name)
            ),
            "foreign_keys": sorted(
                (
                    str(key["name"]),
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
            "checks": sorted(
                (str(check["name"]), check["sqltext"])
                for check in inspector.get_check_constraints(table_name)
            ),
            "indexes": sorted(
                (
                    str(index["name"]),
                    tuple(str(column) for column in index["column_names"]),
                    bool(index["unique"]),
                    str(index.get("dialect_options", {}).get("postgresql_where")),
                )
                for index in inspector.get_indexes(table_name)
            ),
        }
        for table_name in inspector.get_table_names()
    }


def _current_revision(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(
            connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        )


def _insert_dynamic(
    connection: Connection,
    rows: PublicApiRows,
    *,
    content_hash: str = "d" * 64,
    country_id: str = "us",
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
        content_hash=content_hash,
    )
    return dynamic_id


def _insert_parameter(connection: Connection, rows: PublicApiRows) -> object:
    parameter_id = uuid4()
    insert_row(
        connection,
        "parameters",
        id=parameter_id,
        name="gov.simulation.labor_supply_responses.elasticities.income",
        tax_benefit_model_version_id=rows.version_id,
    )
    return parameter_id


def _insert_policy(
    connection: Connection, rows: PublicApiRows, *, country_id: str
) -> object:
    policy_id = uuid4()
    insert_row(
        connection,
        "policies",
        id=policy_id,
        country_id=country_id,
        tax_benefit_model_id=rows.model_id,
        tax_benefit_model_version_id=rows.version_id,
        canonicalization_version=1,
        content_hash=uuid4().hex * 2,
    )
    return policy_id


def test_the_revision_changes_only_dynamics_their_values_and_mappings(
    engine: Engine,
) -> None:
    config = alembic_v2_config()
    command.downgrade(config, PREVIOUS_REVISION)
    before = _schema(engine)
    command.upgrade(config, DYNAMICS_REVISION)
    after = _schema(engine)

    assert {name: before[name] for name in before if name not in CHANGED_TABLES} == {
        name: after[name] for name in after if name not in CHANGED_TABLES
    }
    assert {column[0] for column in after["dynamics"]["columns"]} == {
        column[0] for column in after["policies"]["columns"]
    }
    assert {column[0] for column in before["dynamics"]["columns"]} == {
        "id",
        "created_at",
        "updated_at",
        "name",
        "description",
    }
    assert set(after["legacy_policy_mappings"]["columns"]) - set(
        before["legacy_policy_mappings"]["columns"]
    ) == {("dynamic_id", "UUID", True)}
    assert set(after["legacy_policy_mappings"]["foreign_keys"]) - set(
        before["legacy_policy_mappings"]["foreign_keys"]
    ) == {
        (
            "fk_legacy_policy_mappings_dynamic_country",
            ("dynamic_id", "country_id"),
            "dynamics",
            ("id", "country_id"),
            "RESTRICT",
        )
    }
    assert set(after["parameter_values"]["indexes"]) - set(
        before["parameter_values"]["indexes"]
    ) == {
        (
            "uq_parameter_values_dynamic_parameter_start_date",
            ("dynamic_id", "parameter_id", "start_date"),
            True,
            "(dynamic_id IS NOT NULL)",
        )
    }
    assert {
        key: value
        for key, value in after["parameter_values"].items()
        if key != "indexes"
    } == {
        key: value
        for key, value in before["parameter_values"].items()
        if key != "indexes"
    }

    command.downgrade(config, PREVIOUS_REVISION)
    assert _schema(engine) == before
    command.upgrade(config, "head")
    command.check(config)


def test_a_dynamic_is_stored_once_and_sets_one_value_per_parameter_and_date(
    connection: Connection,
) -> None:
    rows = insert_public_api_rows(connection)
    parameter_id = _insert_parameter(connection, rows)
    dynamic_id = _insert_dynamic(connection, rows)

    with refused(connection, match="uq_dynamics_canonicalization_content_hash"):
        _insert_dynamic(connection, rows)
    with refused(connection, match="ck_dynamics_content_hash_length"):
        _insert_dynamic(connection, rows, content_hash="short")

    value = {
        "parameter_id": parameter_id,
        "dynamic_id": dynamic_id,
        "value_json": "0.1",
        "start_date": "2026-01-01T00:00:00Z",
    }
    insert_row(connection, "parameter_values", id=uuid4(), **value)
    with refused(connection, match="uq_parameter_values_dynamic_parameter_start_date"):
        insert_row(connection, "parameter_values", id=uuid4(), **value)
    # Another dynamic may set the same parameter from the same date.
    other_dynamic_id = _insert_dynamic(connection, rows, content_hash="e" * 64)
    insert_row(
        connection,
        "parameter_values",
        id=uuid4(),
        **{**value, "dynamic_id": other_dynamic_id},
    )


def test_a_mapping_names_a_dynamic_of_its_country_which_stays_while_named(
    connection: Connection,
) -> None:
    rows = insert_public_api_rows(connection)
    us_dynamic_id = _insert_dynamic(connection, rows)
    us_policy_id = _insert_policy(connection, rows, country_id="us")
    uk_policy_id = _insert_policy(connection, rows, country_id="uk")

    with refused(connection, match="fk_legacy_policy_mappings_dynamic_country"):
        insert_row(
            connection,
            "legacy_policy_mappings",
            id=uuid4(),
            country_id="uk",
            legacy_policy_id=1,
            policy_id=uk_policy_id,
            dynamic_id=us_dynamic_id,
            source_policy_hash="v1-hash",
        )
    insert_row(
        connection,
        "legacy_policy_mappings",
        id=uuid4(),
        country_id="us",
        legacy_policy_id=1,
        policy_id=us_policy_id,
        dynamic_id=us_dynamic_id,
        source_policy_hash="v1-hash",
    )
    # A mapping without a dynamic is unaffected.
    insert_row(
        connection,
        "legacy_policy_mappings",
        id=uuid4(),
        country_id="us",
        legacy_policy_id=2,
        policy_id=us_policy_id,
        source_policy_hash="v1-hash-2",
    )
    with refused(connection, match="fk_legacy_policy_mappings_dynamic_country"):
        connection.execute(
            text("DELETE FROM dynamics WHERE id = :id"), {"id": us_dynamic_id}
        )


def test_the_upgrade_fails_changing_nothing_while_a_dynamic_is_stored(
    engine: Engine,
) -> None:
    config = alembic_v2_config()
    command.downgrade(config, PREVIOUS_REVISION)
    dynamic_id = uuid4()
    with engine.begin() as connection:
        insert_row(connection, "dynamics", id=dynamic_id, name="stored before")
    try:
        with pytest.raises(IntegrityError, match="country_id"):
            command.upgrade(config, DYNAMICS_REVISION)
        assert _current_revision(engine) == PREVIOUS_REVISION
        dynamics_columns = inspect(engine).get_columns("dynamics")
        assert "name" in {column["name"] for column in dynamics_columns}
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM dynamics WHERE id = :id"), {"id": dynamic_id}
            )


def test_the_downgrade_fails_changing_nothing_while_a_dynamic_is_stored(
    engine: Engine,
) -> None:
    config = alembic_v2_config()
    # The fixture upgrades to the head before the test, and the head can be
    # later than the dynamics revision, so a downgrade reaches it; an upgrade
    # to an older revision does nothing.
    command.downgrade(config, DYNAMICS_REVISION)
    with engine.begin() as connection:
        rows = insert_public_api_rows(connection)
        dynamic_id = _insert_dynamic(connection, rows)
    try:
        with pytest.raises(IntegrityError, match="name"):
            command.downgrade(config, PREVIOUS_REVISION)
        assert _current_revision(engine) == DYNAMICS_REVISION
        mapping_columns = inspect(engine).get_columns("legacy_policy_mappings")
        assert "dynamic_id" in {column["name"] for column in mapping_columns}
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM dynamics WHERE id = :id"), {"id": dynamic_id}
            )
            delete_public_api_rows(connection, rows)
