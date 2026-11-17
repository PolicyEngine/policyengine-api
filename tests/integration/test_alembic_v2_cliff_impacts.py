"""Check the cliff impacts revision against disposable Postgres.

Revision bc334f9877b7, on the user invitations revision f519a77ba122, adds
``cliff_impacts``: one row per cliff calculation of a simulation run, with its
state and, once it succeeds, the run's cliff gap and cliff share. Its status
reuses the ``v2_simulation_status`` type, and it changes no other table. The
downgrade drops the table with its rows and leaves the type, which
``simulation_runs`` still uses.
"""

from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from sqlalchemy import Connection, Engine, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
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

USER_INVITATIONS_REVISION = "f519a77ba122"
CLIFF_IMPACTS_REVISION = "bc334f9877b7"
# What a request starting a run's cliff calculation inserts: the conflict
# target names the partial unique index's whole condition.
START_CLIFF_CALCULATION = (
    "INSERT INTO cliff_impacts (id, simulation_run_id, status) "
    "VALUES (:id, :simulation_run_id, 'pending') "
    "ON CONFLICT (simulation_run_id) WHERE status <> 'failed' DO NOTHING "
    "RETURNING id"
)


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
                (
                    index["name"],
                    index["column_names"],
                    index["unique"],
                    index.get("dialect_options", {}).get("postgresql_where"),
                )
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
    database_engine = create_engine(disposable_v2_url(), poolclass=NullPool)
    try:
        yield database_engine
    finally:
        command.upgrade(alembic_v2_config(), "head")
        database_engine.dispose()


def test_cliff_impacts_revision_adds_only_its_table(engine: Engine) -> None:
    """The revision adds one table, with no new enum type, and changes nothing else."""
    config = alembic_v2_config()

    command.upgrade(config, "head")
    command.downgrade(config, USER_INVITATIONS_REVISION)
    parent_shape = _schema_shape(engine)
    parent_enums = _enum_labels(engine)
    command.upgrade(config, CLIFF_IMPACTS_REVISION)
    revision_shape = _schema_shape(engine)

    assert set(revision_shape) - set(parent_shape) == {"cliff_impacts"}
    assert {
        table_name: shape
        for table_name, shape in revision_shape.items()
        if table_name != "cliff_impacts"
    } == parent_shape
    assert _enum_labels(engine) == parent_enums
    cliff_impacts = revision_shape["cliff_impacts"]
    assert cliff_impacts["primary_key"]["constrained_columns"] == ["id"]
    assert [
        (columns, referred_table, ondelete)
        for _name, columns, referred_table, ondelete in cliff_impacts["foreign_keys"]
    ] == [(["simulation_run_id"], "simulation_runs", "CASCADE")]
    assert cliff_impacts["unique_constraints"] == []
    assert cliff_impacts["indexes"] == [
        ("ix_cliff_impacts_simulation_run_id", ["simulation_run_id"], False, None),
        ("ix_cliff_impacts_status_started_at", ["status", "started_at"], False, None),
        (
            "uq_cliff_impacts_unfailed",
            ["simulation_run_id"],
            True,
            "(status <> 'failed'::v2_simulation_status)",
        ),
    ]
    assert set(cliff_impacts["checks"]) == {
        "ck_cliff_impacts_finished_completion",
        "ck_cliff_impacts_result_when_succeeded",
    }
    with engine.connect() as connection:
        column_types = dict(
            connection.execute(
                text(
                    "SELECT column_name, udt_name || ':' || is_nullable "
                    "FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'cliff_impacts'"
                )
            ).all()
        )
    assert column_types == {
        "id": "uuid:NO",
        "created_at": "timestamptz:NO",
        "updated_at": "timestamptz:NO",
        "simulation_run_id": "uuid:NO",
        "status": "v2_simulation_status:NO",
        "modal_call_id": "varchar:YES",
        "error_message": "varchar:YES",
        "started_at": "timestamptz:YES",
        "completed_at": "timestamptz:YES",
        "cliff_gap": "float8:YES",
        "cliff_share": "float8:YES",
    }


def test_cliff_impacts_downgrade_drops_the_table_and_keeps_the_status_type(
    engine: Engine,
) -> None:
    """Downgrading drops only the table, so upgrading again works."""
    config = alembic_v2_config()

    command.upgrade(config, "head")
    command.downgrade(config, USER_INVITATIONS_REVISION)

    assert "cliff_impacts" not in inspect(engine).get_table_names()
    # ``simulation_runs.status`` still uses the type.
    assert _enum_labels(engine)["v2_simulation_status"] == [
        "pending",
        "running",
        "succeeded",
        "failed",
    ]

    command.upgrade(config, CLIFF_IMPACTS_REVISION)

    assert "cliff_impacts" in inspect(engine).get_table_names()


def _insert_simulation_run(connection: Connection) -> UUID:
    """Store an economy simulation and one pending run of it."""
    public_api_rows = insert_public_api_rows(connection)
    simulation_id = uuid4()
    run_id = uuid4()
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
        id=run_id,
        simulation_id=simulation_id,
        tax_benefit_model_version_id=public_api_rows.version_id,
        year=2026,
        status="pending",
        **RUN_VERSIONS,
    )
    return run_id


def _start_cliff_calculation(connection: Connection, run_id: UUID) -> UUID | None:
    """Insert a pending calculation unless one that hasn't failed exists."""
    return connection.execute(
        text(START_CLIFF_CALCULATION), {"id": uuid4(), "simulation_run_id": run_id}
    ).scalar_one_or_none()


def _fail_cliff_calculation(connection: Connection, calculation_id: UUID) -> None:
    connection.execute(
        text(
            "UPDATE cliff_impacts SET status = 'failed', "
            "error_message = 'modal_call_ended: the call ended', "
            "completed_at = now() WHERE id = :id"
        ),
        {"id": calculation_id},
    )


def _cliff_statuses(connection: Connection, run_id: UUID) -> list[str]:
    return list(
        connection.execute(
            text(
                "SELECT status::text FROM cliff_impacts "
                "WHERE simulation_run_id = :run_id ORDER BY created_at, status"
            ),
            {"run_id": run_id},
        ).scalars()
    )


def test_a_run_starts_one_cliff_calculation_until_it_fails(engine: Engine) -> None:
    """Two requests at once start one calculation; a failed one never counts."""
    command.upgrade(alembic_v2_config(), "head")

    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            run_id = _insert_simulation_run(connection)
            first_calculation = _start_cliff_calculation(connection, run_id)
            joined_calculation = _start_cliff_calculation(connection, run_id)

            assert first_calculation is not None
            # The second request joins the pending calculation.
            assert joined_calculation is None
            with refused(connection, IntegrityError, match="uq_cliff_impacts_unfailed"):
                insert_row(
                    connection,
                    "cliff_impacts",
                    id=uuid4(),
                    simulation_run_id=run_id,
                    status="running",
                )

            _fail_cliff_calculation(connection, first_calculation)
            retried_calculation = _start_cliff_calculation(connection, run_id)

            assert retried_calculation is not None
            connection.execute(
                text(
                    "UPDATE cliff_impacts SET status = 'succeeded', "
                    "cliff_gap = 1.5e9, cliff_share = 0.04, completed_at = now() "
                    "WHERE id = :id"
                ),
                {"id": retried_calculation},
            )
            assert _start_cliff_calculation(connection, run_id) is None
            assert sorted(_cliff_statuses(connection, run_id)) == [
                "failed",
                "succeeded",
            ]
        finally:
            transaction.rollback()


@pytest.mark.parametrize(
    ("assignments", "check_name"),
    [
        ("status = 'succeeded', completed_at = now()", "result_when_succeeded"),
        (
            "status = 'succeeded', cliff_gap = 1.0, completed_at = now()",
            "result_when_succeeded",
        ),
        ("cliff_gap = 1.0, cliff_share = 0.1", "result_when_succeeded"),
        (
            "status = 'failed', cliff_gap = 1.0, cliff_share = 0.1, "
            "completed_at = now()",
            "result_when_succeeded",
        ),
        ("status = 'failed'", "finished_completion"),
        (
            "status = 'succeeded', cliff_gap = 1.0, cliff_share = 0.1",
            "finished_completion",
        ),
    ],
)
def test_only_a_finished_calculation_ends_and_only_a_succeeded_one_has_numbers(
    engine: Engine, assignments: str, check_name: str
) -> None:
    command.upgrade(alembic_v2_config(), "head")

    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            run_id = _insert_simulation_run(connection)
            calculation_id = _start_cliff_calculation(connection, run_id)

            with refused(
                connection, IntegrityError, match=f"ck_cliff_impacts_{check_name}"
            ):
                connection.execute(
                    text(f"UPDATE cliff_impacts SET {assignments} WHERE id = :id"),
                    {"id": calculation_id},
                )
        finally:
            transaction.rollback()


def test_a_runs_cliff_calculations_are_deleted_with_it(engine: Engine) -> None:
    command.upgrade(alembic_v2_config(), "head")

    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            run_id = _insert_simulation_run(connection)
            failed_calculation = _start_cliff_calculation(connection, run_id)
            assert failed_calculation is not None
            _fail_cliff_calculation(connection, failed_calculation)
            _start_cliff_calculation(connection, run_id)

            connection.execute(
                text("DELETE FROM simulation_runs WHERE id = :id"), {"id": run_id}
            )

            assert _cliff_statuses(connection, run_id) == []
        finally:
            transaction.rollback()
