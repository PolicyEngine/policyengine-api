"""Check the withheld area codes revision against disposable Postgres.

Revision 1e1e3f079f2c, on the SPM availability revision 0c136a278f29, adds
``withheld_area_codes`` and its ``v2_uk_area_type`` enum and changes no other
table. Each row names a UK area that disclosure control withheld from a
report run's local-area results. The downgrade drops the table, with its rows,
then the type.
"""

from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from sqlalchemy import Connection, Engine, create_engine, inspect, text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.pool import NullPool

from tests.fixtures.integration.alembic_v2 import (
    alembic_v2_config,
    disposable_v2_url,
)
from tests.integration.simulation_rows import (
    RUN_VERSIONS,
    insert_public_api_rows,
    insert_row,
    refused,
)

SPM_AVAILABILITY_REVISION = "0c136a278f29"
WITHHELD_AREA_CODES_REVISION = "1e1e3f079f2c"


def _schema_shape(engine: Engine) -> dict[str, dict[str, Any]]:
    """Reflect every table's columns, keys, indexes and checks."""
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
                (
                    key["name"],
                    key["constrained_columns"],
                    key["referred_table"],
                    key["options"].get("ondelete"),
                )
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


def _enum_labels(engine: Engine) -> dict[str, list[str]]:
    """Return each enum type in the public schema with its labels in order."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT type.typname, enum.enumlabel FROM pg_type AS type "
                "JOIN pg_enum AS enum ON enum.enumtypid = type.oid "
                "JOIN pg_namespace AS namespace ON namespace.oid = type.typnamespace "
                "WHERE namespace.nspname = 'public' "
                "ORDER BY type.typname, enum.enumsortorder"
            )
        ).all()
    labels: dict[str, list[str]] = {}
    for type_name, label in rows:
        labels.setdefault(type_name, []).append(label)
    return labels


@pytest.fixture
def engine() -> Iterator[Engine]:
    """Yield an engine on the disposable database, left at the v2 head."""
    database_url = disposable_v2_url()
    database_engine = create_engine(database_url, poolclass=NullPool)
    try:
        yield database_engine
    finally:
        command.upgrade(alembic_v2_config(), "head")
        database_engine.dispose()


def test_withheld_area_codes_revision_adds_only_the_table_and_its_type(
    engine: Engine,
) -> None:
    """The revision adds one table and one enum type and changes nothing else."""
    config = alembic_v2_config()

    command.upgrade(config, "head")
    command.downgrade(config, SPM_AVAILABILITY_REVISION)
    parent_shape = _schema_shape(engine)
    parent_enums = _enum_labels(engine)
    command.upgrade(config, WITHHELD_AREA_CODES_REVISION)
    revision_shape = _schema_shape(engine)
    revision_enums = _enum_labels(engine)

    assert set(revision_shape) - set(parent_shape) == {"withheld_area_codes"}
    assert {
        table_name: shape
        for table_name, shape in revision_shape.items()
        if table_name != "withheld_area_codes"
    } == parent_shape
    assert revision_enums == {
        **parent_enums,
        "v2_uk_area_type": ["constituency", "local_authority"],
    }
    withheld = revision_shape["withheld_area_codes"]
    assert withheld["primary_key"]["constrained_columns"] == ["id"]
    assert withheld["unique_constraints"] == [
        (
            "uq_withheld_area_codes_run_type_code",
            ["report_run_id", "area_type", "code"],
        )
    ]
    assert sorted(
        (columns, referred_table, ondelete)
        for _name, columns, referred_table, ondelete in withheld["foreign_keys"]
    ) == [
        (["baseline_simulation_run_id"], "simulation_runs", "RESTRICT"),
        (["reform_simulation_run_id"], "simulation_runs", "RESTRICT"),
        (["report_run_id"], "report_runs", "CASCADE"),
    ]


def test_withheld_area_codes_downgrade_removes_the_table_and_its_type(
    engine: Engine,
) -> None:
    """Downgrading drops the table and the type, so upgrading again works."""
    config = alembic_v2_config()

    command.upgrade(config, "head")
    command.downgrade(config, WITHHELD_AREA_CODES_REVISION)
    command.downgrade(config, SPM_AVAILABILITY_REVISION)

    assert "withheld_area_codes" not in inspect(engine).get_table_names()
    assert "v2_uk_area_type" not in _enum_labels(engine)

    command.upgrade(config, WITHHELD_AREA_CODES_REVISION)

    assert "withheld_area_codes" in inspect(engine).get_table_names()
    assert _enum_labels(engine)["v2_uk_area_type"] == [
        "constituency",
        "local_authority",
    ]


def _insert_report_run(connection: Connection) -> dict[str, UUID]:
    """Store a UK report run comparing two simulation runs, and a spare run."""
    public_api_rows = insert_public_api_rows(connection)
    run_names = ("baseline_run", "reform_run", "unrelated_run")
    ids = {name: uuid4() for name in (*run_names, "report", "report_run")}
    # Each run is of a simulation of its own: a simulation has one unfailed
    # run per version set.
    for run_name in run_names:
        simulation_id = uuid4()
        insert_row(
            connection,
            "simulations",
            id=simulation_id,
            simulation_type="economy",
            dataset_id=public_api_rows.dataset_id,
            tax_benefit_model_version_id=public_api_rows.version_id,
            year=2026,
        )
        insert_row(
            connection,
            "simulation_runs",
            id=ids[run_name],
            simulation_id=simulation_id,
            tax_benefit_model_version_id=public_api_rows.version_id,
            year=2026,
            status="pending",
            **RUN_VERSIONS,
        )
    insert_row(
        connection,
        "reports",
        id=ids["report"],
        label="Local areas",
        country="uk",
        tax_benefit_model_id=public_api_rows.model_id,
        year=2026,
        inputs="{}",
    )
    insert_row(
        connection,
        "report_runs",
        id=ids["report_run"],
        report_id=ids["report"],
        baseline_simulation_run_id=ids["baseline_run"],
        reform_simulation_run_id=ids["reform_run"],
        status="pending",
        trigger="initial",
        **RUN_VERSIONS,
    )
    return ids


def _insert_withheld_code(
    connection: Connection,
    ids: dict[str, UUID],
    *,
    area_type: str,
    code: str,
    reform_run: str = "reform_run",
) -> None:
    insert_row(
        connection,
        "withheld_area_codes",
        id=uuid4(),
        report_run_id=ids["report_run"],
        baseline_simulation_run_id=ids["baseline_run"],
        reform_simulation_run_id=ids[reform_run],
        area_type=area_type,
        code=code,
    )


def _withheld_codes(connection: Connection, report_run_id: UUID) -> list[tuple]:
    return connection.execute(
        text(
            "SELECT area_type::text, code FROM withheld_area_codes "
            "WHERE report_run_id = :report_run_id ORDER BY area_type, code"
        ),
        {"report_run_id": report_run_id},
    ).all()


def test_withheld_area_codes_hold_each_area_once_and_go_with_their_run(
    engine: Engine,
) -> None:
    """Each run lists an area once, of a known type; deleting the run drops it."""
    command.upgrade(alembic_v2_config(), "head")

    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            ids = _insert_report_run(connection)
            _insert_withheld_code(
                connection, ids, area_type="constituency", code="E14001063"
            )
            # The same code under the other area type is a different area.
            _insert_withheld_code(
                connection, ids, area_type="local_authority", code="E14001063"
            )
            _insert_withheld_code(
                connection,
                ids,
                area_type="local_authority",
                code="E06000001",
                reform_run="unrelated_run",
            )

            with refused(connection, IntegrityError, match="uq_withheld_area_codes"):
                _insert_withheld_code(
                    connection, ids, area_type="constituency", code="E14001063"
                )
            with refused(connection, DataError, match="v2_uk_area_type"):
                _insert_withheld_code(
                    connection, ids, area_type="ward", code="E05000001"
                )
            # A simulation run that withheld codes name stays while they do.
            with refused(connection, IntegrityError, match="withheld_area_codes"):
                connection.execute(
                    text("DELETE FROM simulation_runs WHERE id = :id"),
                    {"id": ids["unrelated_run"]},
                )
            assert _withheld_codes(connection, ids["report_run"]) == [
                ("constituency", "E14001063"),
                ("local_authority", "E06000001"),
                ("local_authority", "E14001063"),
            ]

            connection.execute(
                text("DELETE FROM report_runs WHERE id = :id"),
                {"id": ids["report_run"]},
            )

            assert _withheld_codes(connection, ids["report_run"]) == []
        finally:
            transaction.rollback()
