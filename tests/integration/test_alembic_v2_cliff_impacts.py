"""Check the cliff impacts revision against disposable Postgres.

Revision bc334f9877b7, on the dynamics revision 9d1d12a7ac58, adds
``cliff_impacts``: one row per cliff calculation of a simulation run, with its
state and, once it succeeds, the run's cliff gap and cliff share. Its status
reuses the ``v2_simulation_status`` type, and it changes no other table. The
downgrade drops the table with its rows and leaves the type, which
``simulation_runs`` still uses.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from sqlalchemy import delete, func, literal, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql.base import PGInspector
from sqlalchemy.exc import IntegrityError
from sqlmodel import col

from policyengine_api.data.v2.models import (
    CliffImpact,
    Simulation,
    SimulationRun,
    SimulationStatus,
)
from tests.fixtures.database_sessions import schema_inspector
from tests.fixtures.integration.alembic_v2 import alembic_v2_config, table_columns
from tests.integration.simulation_rows import (
    RUN_VERSIONS,
    add_row,
    insert_public_api_rows,
    refused,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

DYNAMICS_REVISION = "9d1d12a7ac58"
CLIFF_IMPACTS_REVISION = "bc334f9877b7"


def _schema_shape(sessions: sessionmaker[Session]) -> dict[str, dict[str, Any]]:
    """Reflect every table's columns, keys, indexes and checks."""
    with sessions() as session:
        inspector = schema_inspector(session)
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


def _enum_labels(sessions: sessionmaker[Session]) -> dict[str, list[str]]:
    """Return each enum type in the public schema with its labels in order."""
    inspector = schema_inspector(sessions)
    assert isinstance(inspector, PGInspector)
    return {
        enum_type["name"]: enum_type["labels"]
        for enum_type in inspector.get_enums(schema="public")
    }


def _table_names(sessions: sessionmaker[Session]) -> list[str]:
    return schema_inspector(sessions).get_table_names()


@pytest.fixture
def sessions(
    v2_owner_sessions: sessionmaker[Session],
) -> Iterator[sessionmaker[Session]]:
    """Yield the disposable database owner's Session factories; leave it at head."""
    try:
        yield v2_owner_sessions
    finally:
        command.upgrade(alembic_v2_config(), "head")


@pytest.fixture
def session(sessions: sessionmaker[Session]) -> Iterator[Session]:
    """Yield a Session at the v2 head whose writes are rolled back after the test."""
    command.upgrade(alembic_v2_config(), "head")
    with sessions() as database_session:
        try:
            yield database_session
        finally:
            database_session.rollback()


def test_cliff_impacts_revision_adds_only_its_table(
    sessions: sessionmaker[Session],
) -> None:
    """The revision adds one table, with no new enum type, and changes nothing else."""
    config = alembic_v2_config()

    command.upgrade(config, "head")
    command.downgrade(config, DYNAMICS_REVISION)
    parent_shape = _schema_shape(sessions)
    parent_enums = _enum_labels(sessions)
    command.upgrade(config, CLIFF_IMPACTS_REVISION)
    revision_shape = _schema_shape(sessions)

    assert set(revision_shape) - set(parent_shape) == {"cliff_impacts"}
    assert {
        table_name: shape
        for table_name, shape in revision_shape.items()
        if table_name != "cliff_impacts"
    } == parent_shape
    assert _enum_labels(sessions) == parent_enums
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
    column_types = {
        column_name: (
            column["type"].compile(dialect=postgresql.dialect()),
            column["nullable"],
        )
        for column_name, column in table_columns(sessions, "cliff_impacts").items()
    }
    assert column_types == {
        "id": ("UUID", False),
        "created_at": ("TIMESTAMP WITH TIME ZONE", False),
        "updated_at": ("TIMESTAMP WITH TIME ZONE", False),
        "simulation_run_id": ("UUID", False),
        "status": ("v2_simulation_status", False),
        "modal_call_id": ("VARCHAR(255)", True),
        "error_message": ("VARCHAR", True),
        "started_at": ("TIMESTAMP WITH TIME ZONE", True),
        "completed_at": ("TIMESTAMP WITH TIME ZONE", True),
        "cliff_gap": ("DOUBLE PRECISION", True),
        "cliff_share": ("DOUBLE PRECISION", True),
    }


def test_cliff_impacts_downgrade_drops_the_table_and_keeps_the_status_type(
    sessions: sessionmaker[Session],
) -> None:
    """Downgrading drops only the table, so upgrading again works."""
    config = alembic_v2_config()

    command.upgrade(config, "head")
    command.downgrade(config, DYNAMICS_REVISION)

    assert "cliff_impacts" not in _table_names(sessions)
    # ``simulation_runs.status`` still uses the type.
    assert _enum_labels(sessions)["v2_simulation_status"] == [
        "pending",
        "running",
        "succeeded",
        "failed",
    ]

    command.upgrade(config, CLIFF_IMPACTS_REVISION)

    assert "cliff_impacts" in _table_names(sessions)


def _insert_simulation_run(session: Session) -> UUID:
    """Store an economy simulation and one pending run of it."""
    public_api_rows = insert_public_api_rows(session)
    simulation_id = uuid4()
    run_id = uuid4()
    add_row(
        session,
        Simulation,
        id=simulation_id,
        simulation_type="economy",
        dataset_id=public_api_rows.dataset_id,
        tax_benefit_model_version_id=public_api_rows.version_id,
        year=2026,
    )
    add_row(
        session,
        SimulationRun,
        id=run_id,
        simulation_id=simulation_id,
        tax_benefit_model_version_id=public_api_rows.version_id,
        year=2026,
        status="pending",
        **RUN_VERSIONS,
    )
    return run_id


def _start_cliff_calculation(session: Session, run_id: UUID) -> UUID | None:
    """Insert a pending calculation unless one that hasn't failed exists.

    This is what a request starting a run's cliff calculation inserts
    (INSERT ... ON CONFLICT DO NOTHING RETURNING id): the conflict target
    names the partial unique index's whole condition, ``status <> 'failed'``.
    The status is written into the statement as a literal: PostgreSQL matches
    the condition to the index when it plans the statement, so a parameter
    there fails once psycopg prepares the statement, after five runs on one
    connection, and PostgreSQL plans it without the parameter's value.
    """
    failed_status = literal(SimulationStatus.FAILED, literal_execute=True)
    start_calculation = (
        postgresql.insert(CliffImpact)
        .values(id=uuid4(), simulation_run_id=run_id, status=SimulationStatus.PENDING)
        .on_conflict_do_nothing(
            index_elements=["simulation_run_id"],
            index_where=col(CliffImpact.status) != failed_status,
        )
        .returning(col(CliffImpact.id))
    )
    return session.scalars(start_calculation).one_or_none()


def _finish_cliff_calculation(
    session: Session, calculation_id: UUID | None, **assignments: object
) -> None:
    """Update the calculation's columns (UPDATE cliff_impacts SET ...)."""
    session.execute(
        update(CliffImpact)
        .where(col(CliffImpact.id) == calculation_id)
        .values(**assignments)
    )


def _fail_cliff_calculation(session: Session, calculation_id: UUID) -> None:
    _finish_cliff_calculation(
        session,
        calculation_id,
        status=SimulationStatus.FAILED,
        error_message="modal_call_ended: the call ended",
        completed_at=func.now(),
    )


def _cliff_statuses(session: Session, run_id: UUID) -> list[str]:
    return list(
        session.scalars(
            select(col(CliffImpact.status))
            .where(col(CliffImpact.simulation_run_id) == run_id)
            .order_by(col(CliffImpact.created_at), col(CliffImpact.status))
        )
    )


def test_a_run_starts_one_cliff_calculation_until_it_fails(session: Session) -> None:
    """Two requests at once start one calculation; a failed one never counts."""
    run_id = _insert_simulation_run(session)
    first_calculation = _start_cliff_calculation(session, run_id)
    joined_calculation = _start_cliff_calculation(session, run_id)

    assert first_calculation is not None
    # The second request joins the pending calculation.
    assert joined_calculation is None
    with refused(session, IntegrityError, match="uq_cliff_impacts_unfailed"):
        add_row(
            session,
            CliffImpact,
            id=uuid4(),
            simulation_run_id=run_id,
            status="running",
        )

    _fail_cliff_calculation(session, first_calculation)
    retried_calculation = _start_cliff_calculation(session, run_id)

    assert retried_calculation is not None
    _finish_cliff_calculation(
        session,
        retried_calculation,
        status=SimulationStatus.SUCCEEDED,
        cliff_gap=1.5e9,
        cliff_share=0.04,
        completed_at=func.now(),
    )
    assert _start_cliff_calculation(session, run_id) is None
    assert sorted(_cliff_statuses(session, run_id)) == ["failed", "succeeded"]


@pytest.mark.parametrize(
    ("assignments", "check_name"),
    [
        pytest.param(
            {"status": SimulationStatus.SUCCEEDED, "completed_at": func.now()},
            "result_when_succeeded",
            id="succeeded-with-no-numbers",
        ),
        pytest.param(
            {
                "status": SimulationStatus.SUCCEEDED,
                "cliff_gap": 1.0,
                "completed_at": func.now(),
            },
            "result_when_succeeded",
            id="succeeded-with-a-gap-alone",
        ),
        pytest.param(
            {"cliff_gap": 1.0, "cliff_share": 0.1},
            "result_when_succeeded",
            id="pending-with-numbers",
        ),
        pytest.param(
            {
                "status": SimulationStatus.FAILED,
                "cliff_gap": 1.0,
                "cliff_share": 0.1,
                "completed_at": func.now(),
            },
            "result_when_succeeded",
            id="failed-with-numbers",
        ),
        pytest.param(
            {"status": SimulationStatus.FAILED},
            "finished_completion",
            id="failed-with-no-completion-time",
        ),
        pytest.param(
            {
                "status": SimulationStatus.SUCCEEDED,
                "cliff_gap": 1.0,
                "cliff_share": 0.1,
            },
            "finished_completion",
            id="succeeded-with-no-completion-time",
        ),
    ],
)
def test_only_a_finished_calculation_ends_and_only_a_succeeded_one_has_numbers(
    session: Session, assignments: dict[str, object], check_name: str
) -> None:
    run_id = _insert_simulation_run(session)
    calculation_id = _start_cliff_calculation(session, run_id)

    with refused(session, IntegrityError, match=f"ck_cliff_impacts_{check_name}"):
        _finish_cliff_calculation(session, calculation_id, **assignments)


def test_a_runs_cliff_calculations_are_deleted_with_it(session: Session) -> None:
    run_id = _insert_simulation_run(session)
    failed_calculation = _start_cliff_calculation(session, run_id)
    assert failed_calculation is not None
    _fail_cliff_calculation(session, failed_calculation)
    _start_cliff_calculation(session, run_id)

    session.execute(delete(SimulationRun).where(col(SimulationRun.id) == run_id))

    assert _cliff_statuses(session, run_id) == []
