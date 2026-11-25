"""Each simulation run can have one cliff result (C1 · 24's answer 4b).

A cliff calculation of a simulation run records its state and, once it
succeeds, the run's cliff gap and cliff share. A run has at most one
calculation that hasn't failed, so two requests asking for its cliffs at once
start one calculation; a failed calculation never counts, and the next request
starts another. The result inherits its run's versions, and is linked to the
run, not to any report.

Columns are read from the model's mapper, constraints and indexes from SQLite's
copy of the schema, and the partial index from the model's declaration
(tests/unit/v2/v2_schema_reading.py).
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from policyengine_api.data.v2.models import (
    CliffImpact,
    SimulationRun,
    SimulationStatus,
)
from tests.fixtures.database_sessions import sqlite_v2_sessions
from tests.unit.v2.v2_schema_reading import (
    declared_index,
    model_columns,
    stored_v2_table,
)

CLIFF_IMPACT_COLUMNS = frozenset(
    {
        "id",
        "created_at",
        "updated_at",
        "simulation_run_id",
        "status",
        "modal_call_id",
        "error_message",
        "started_at",
        "completed_at",
        "cliff_gap",
        "cliff_share",
    }
)
UNFAILED_CALCULATIONS = "status <> 'failed'"
FINISHED_STATUSES = frozenset({SimulationStatus.SUCCEEDED, SimulationStatus.FAILED})


def test_cliff_impacts_hold_one_calculation_of_a_simulation_run() -> None:
    """The run it calculates, the calculation's state and the two numbers."""
    cliff_impacts = model_columns(CliffImpact)

    assert set(cliff_impacts.keys()) == CLIFF_IMPACT_COLUMNS
    assert not cliff_impacts.simulation_run_id.nullable
    run_key = stored_v2_table("cliff_impacts").foreign_key("simulation_run_id")
    assert run_key.target == "simulation_runs.id"
    # The result is part of its run, as poverty and inequality rows are.
    assert run_key.ondelete == "CASCADE"
    status = cliff_impacts.status
    assert not status.nullable
    assert isinstance(status.type, sa.Enum)
    # A cliff calculation has a simulation run's states, in the same type.
    assert status.type.name == "v2_simulation_status"
    assert status.type.enums == ["pending", "running", "succeeded", "failed"]
    assert cliff_impacts.modal_call_id.type.length == 255
    for timestamp in ("started_at", "completed_at"):
        assert cliff_impacts[timestamp].nullable
        assert cliff_impacts[timestamp].type.timezone
    for number in ("cliff_gap", "cliff_share"):
        assert cliff_impacts[number].nullable
        assert isinstance(cliff_impacts[number].type, sa.Float)
    # No version of its own: it inherits its run's.
    assert {
        "tax_benefit_model_version_id",
        "country_package_version",
        "policyengine_version",
        "report_run_id",
    }.isdisjoint(cliff_impacts.keys())


def test_only_a_succeeded_cliff_calculation_has_a_result() -> None:
    assert stored_v2_table("cliff_impacts").checks == {
        "ck_cliff_impacts_finished_completion": (
            "status NOT IN ('succeeded', 'failed') OR completed_at IS NOT NULL"
        ),
        "ck_cliff_impacts_result_when_succeeded": (
            "(cliff_gap IS NULL) = (cliff_share IS NULL) "
            "AND (status = 'succeeded') = (cliff_gap IS NOT NULL)"
        ),
    }


def test_a_simulation_run_has_one_cliff_calculation_that_has_not_failed() -> None:
    """The partial unique index the simulation service names on conflict."""
    unfailed = declared_index(CliffImpact, "uq_cliff_impacts_unfailed")

    assert unfailed.unique
    assert tuple(column.name for column in unfailed.columns) == ("simulation_run_id",)
    assert str(unfailed.dialect_options["postgresql"]["where"]) == (
        UNFAILED_CALCULATIONS
    )
    assert str(unfailed.dialect_options["sqlite"]["where"]) == UNFAILED_CALCULATIONS
    # The run's key, for its cascade and for reads that include failed rows,
    # and the stuck-run sweep's search by state and age.
    assert {
        name: index.columns
        for name, index in stored_v2_table("cliff_impacts").indexes.items()
        if not index.unique
    } == {
        "ix_cliff_impacts_simulation_run_id": ("simulation_run_id",),
        "ix_cliff_impacts_status_started_at": ("status", "started_at"),
    }


def test_a_simulation_runs_cliff_calculations_go_with_it() -> None:
    relationship = sa.inspect(SimulationRun).relationships["cliff_impacts"]

    assert relationship.mapper.class_ is CliffImpact
    assert "delete" in relationship.cascade
    assert sa.inspect(CliffImpact).relationships["simulation_run"].mapper.class_ is (
        SimulationRun
    )


@pytest.fixture
def sqlite_session() -> Iterator[Session]:
    with sqlite_v2_sessions() as sessions, sessions(expire_on_commit=True) as session:
        yield session


def _cliff_calculation(
    simulation_run_id: UUID,
    *,
    status: SimulationStatus = SimulationStatus.PENDING,
    cliff_gap: float | None = None,
    cliff_share: float | None = None,
) -> CliffImpact:
    return CliffImpact(
        simulation_run_id=simulation_run_id,
        status=status,
        completed_at=datetime.now(UTC) if status in FINISHED_STATUSES else None,
        cliff_gap=cliff_gap,
        cliff_share=cliff_share,
    )


def test_sqlite_refuses_a_second_unfailed_cliff_calculation_like_postgres(
    sqlite_session: Session,
) -> None:
    """Failed calculations stay beside the one that hasn't failed."""
    simulation_run_id = uuid4()
    sqlite_session.add_all(
        [
            _cliff_calculation(simulation_run_id, status=SimulationStatus.FAILED),
            _cliff_calculation(simulation_run_id, status=SimulationStatus.FAILED),
            _cliff_calculation(
                simulation_run_id,
                status=SimulationStatus.SUCCEEDED,
                cliff_gap=1.5e9,
                cliff_share=0.04,
            ),
            _cliff_calculation(uuid4(), status=SimulationStatus.RUNNING),
        ]
    )
    sqlite_session.commit()

    sqlite_session.add(_cliff_calculation(simulation_run_id))
    with pytest.raises(IntegrityError, match="UNIQUE constraint failed: cliff_impacts"):
        sqlite_session.commit()


@pytest.mark.parametrize(
    ("status", "cliff_gap", "cliff_share", "check_name"),
    [
        (SimulationStatus.SUCCEEDED, None, None, "ck_cliff_impacts_result_when"),
        (SimulationStatus.SUCCEEDED, 1.0, None, "ck_cliff_impacts_result_when"),
        (SimulationStatus.PENDING, 1.0, 0.1, "ck_cliff_impacts_result_when"),
        (SimulationStatus.FAILED, 1.0, 0.1, "ck_cliff_impacts_result_when"),
        (SimulationStatus.RUNNING, None, 0.1, "ck_cliff_impacts_result_when"),
    ],
)
def test_sqlite_refuses_numbers_on_any_row_but_a_succeeded_one(
    sqlite_session: Session,
    status: SimulationStatus,
    cliff_gap: float | None,
    cliff_share: float | None,
    check_name: str,
) -> None:
    sqlite_session.add(
        _cliff_calculation(
            uuid4(), status=status, cliff_gap=cliff_gap, cliff_share=cliff_share
        )
    )

    with pytest.raises(IntegrityError, match=check_name):
        sqlite_session.commit()


def test_sqlite_refuses_a_finished_cliff_calculation_without_its_end(
    sqlite_session: Session,
) -> None:
    sqlite_session.add(
        CliffImpact(simulation_run_id=uuid4(), status=SimulationStatus.FAILED)
    )

    with pytest.raises(IntegrityError, match="ck_cliff_impacts_finished_completion"):
        sqlite_session.commit()
