"""Read a report run's cliffs from its two simulation runs' cliff calculations.

Each simulation run has at most one cliff calculation that hasn't failed, and
any number of failed ones (``cliff_impacts``). A side reads its run's
unfailed calculation, else its newest failed one, else none. The report run's
cliff impact is the two sides' results once both have succeeded; ``cliffs``
says how far each side's calculation has got.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, get_args
from uuid import UUID, uuid4

import pytest

from policyengine_api.data.v2.models import CliffImpact as CliffImpactRow
from policyengine_api.data.v2.models import SimulationStatus
from policyengine_api.services.v2.stored_reports.database_connectors import (
    reads_results as result_reads,
)
from policyengine_api.services.v2.stored_reports.economy_results import (
    transformations as result_transformations,
)
from policyengine_api.services.v2.stored_reports.economy_results.types import (
    CliffImpact,
    CliffImpactInSimulation,
    ReportRunCliffRows,
)
from policyengine_api.services.v2.stored_reports.transformations import (
    report_cliffs,
)
from policyengine_api.services.v2.stored_reports.types import (
    CliffCalculationRead,
    CliffCalculationStatusName,
    ReportCliffsRead,
)
from tests.unit.v2.sqlite_report_rows import sqlite_sessions

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

CALCULATED_AT = datetime(2026, 11, 17, 9, tzinfo=UTC)
FAILURE = "cliff_calculation_failed: the calculation raised an error"


def cliff_calculation(
    status: SimulationStatus,
    *,
    simulation_run_id: UUID | None = None,
    created_at: datetime = CALCULATED_AT,
    cliff_gap: float = 1_200_000_000.0,
    cliff_share: float = 0.04,
) -> CliffImpactRow:
    """Return a cliff calculation in ``status``, as the table's checks allow it.

    A succeeded one has its two numbers, a failed one its error, and each
    finished one its completion time.
    """
    finished = status in {SimulationStatus.SUCCEEDED, SimulationStatus.FAILED}
    succeeded = status is SimulationStatus.SUCCEEDED
    return CliffImpactRow(
        id=uuid4(),
        created_at=created_at,
        updated_at=created_at,
        simulation_run_id=uuid4() if simulation_run_id is None else simulation_run_id,
        status=status,
        error_message=FAILURE if status is SimulationStatus.FAILED else None,
        started_at=None if status is SimulationStatus.PENDING else created_at,
        completed_at=created_at + timedelta(minutes=1) if finished else None,
        cliff_gap=cliff_gap if succeeded else None,
        cliff_share=cliff_share if succeeded else None,
    )


def side_calculation(status: CliffCalculationStatusName) -> CliffImpactRow | None:
    """Return the calculation a side reads for ``status``: none when not calculated."""
    if status == "not_calculated":
        return None
    return cliff_calculation(SimulationStatus(status))


def side(status: CliffCalculationStatusName) -> CliffCalculationRead:
    """Return a side's read in ``status``, with the error only when failed."""
    return CliffCalculationRead(
        status=status, error_message=FAILURE if status == "failed" else None
    )


@pytest.fixture
def sessions() -> Iterator[sessionmaker[Session]]:
    yield from sqlite_sessions()


def store_calculations(
    sessions: sessionmaker[Session], *calculations: CliffImpactRow
) -> None:
    with sessions() as session:
        session.add_all(calculations)
        session.commit()


def test_sides_without_cliff_calculations_are_not_calculated() -> None:
    cliffs = report_cliffs(ReportRunCliffRows(baseline=None, reform=None))

    assert cliffs == ReportCliffsRead(
        status="not_calculated",
        baseline=side("not_calculated"),
        reform=side("not_calculated"),
    )


@pytest.mark.parametrize(
    "status",
    [SimulationStatus.PENDING, SimulationStatus.RUNNING, SimulationStatus.SUCCEEDED],
    ids=["pending", "running", "succeeded"],
)
def test_a_side_reads_its_unfailed_calculations_status_without_an_error(
    status: SimulationStatus,
) -> None:
    calculation = cliff_calculation(status)

    cliffs = report_cliffs(ReportRunCliffRows(baseline=calculation, reform=calculation))

    assert cliffs.baseline == CliffCalculationRead(
        status=status.value, error_message=None
    )
    assert cliffs.reform == cliffs.baseline


def test_a_failed_side_says_why_its_calculation_failed() -> None:
    cliffs = report_cliffs(
        ReportRunCliffRows(
            baseline=cliff_calculation(SimulationStatus.SUCCEEDED),
            reform=cliff_calculation(SimulationStatus.FAILED),
        )
    )

    assert cliffs.reform == CliffCalculationRead(status="failed", error_message=FAILURE)
    assert cliffs.baseline == side("succeeded")


@pytest.mark.parametrize(
    ("baseline", "reform", "overall"),
    [
        ("succeeded", "succeeded", "succeeded"),
        ("succeeded", "failed", "failed"),
        ("running", "failed", "failed"),
        ("failed", "not_calculated", "failed"),
        ("succeeded", "not_calculated", "not_calculated"),
        ("running", "not_calculated", "not_calculated"),
        ("succeeded", "running", "running"),
        ("pending", "running", "running"),
        ("succeeded", "pending", "pending"),
        ("pending", "pending", "pending"),
    ],
)
def test_the_reports_cliff_status_follows_its_least_finished_side(
    baseline: CliffCalculationStatusName,
    reform: CliffCalculationStatusName,
    overall: CliffCalculationStatusName,
) -> None:
    cliffs = report_cliffs(
        ReportRunCliffRows(
            baseline=side_calculation(baseline), reform=side_calculation(reform)
        )
    )
    swapped = report_cliffs(
        ReportRunCliffRows(
            baseline=side_calculation(reform), reform=side_calculation(baseline)
        )
    )

    assert cliffs == ReportCliffsRead(
        status=overall, baseline=side(baseline), reform=side(reform)
    )
    assert swapped.status == overall


def test_every_side_status_is_one_a_report_can_have() -> None:
    assert set(get_args(CliffCalculationStatusName)) == {
        "not_calculated",
        *(status.value for status in SimulationStatus),
    }


def test_two_succeeded_sides_give_the_report_runs_cliff_impact() -> None:
    cliff_impact = result_transformations.cliff_impact(
        ReportRunCliffRows(
            baseline=cliff_calculation(
                SimulationStatus.SUCCEEDED, cliff_gap=1_200_000_000.0, cliff_share=0.04
            ),
            reform=cliff_calculation(
                SimulationStatus.SUCCEEDED, cliff_gap=1_100_000_000.0, cliff_share=0.035
            ),
        )
    )

    assert cliff_impact == CliffImpact(
        baseline=CliffImpactInSimulation(cliff_gap=1_200_000_000.0, cliff_share=0.04),
        reform=CliffImpactInSimulation(cliff_gap=1_100_000_000.0, cliff_share=0.035),
    )


@pytest.mark.parametrize(
    "unfinished", ["not_calculated", "pending", "running", "failed"]
)
def test_a_side_without_a_result_leaves_the_cliff_impact_null(
    unfinished: CliffCalculationStatusName,
) -> None:
    succeeded = cliff_calculation(SimulationStatus.SUCCEEDED)

    for rows in (
        ReportRunCliffRows(baseline=succeeded, reform=side_calculation(unfinished)),
        ReportRunCliffRows(baseline=side_calculation(unfinished), reform=succeeded),
    ):
        assert result_transformations.cliff_impact(rows) is None


def test_each_side_reads_its_runs_unfailed_calculation_before_a_newer_failed_one(
    sessions: sessionmaker[Session],
) -> None:
    baseline_run_id, reform_run_id = uuid4(), uuid4()
    running = cliff_calculation(
        SimulationStatus.RUNNING, simulation_run_id=baseline_run_id
    )
    succeeded = cliff_calculation(
        SimulationStatus.SUCCEEDED, simulation_run_id=reform_run_id
    )
    store_calculations(
        sessions,
        running,
        succeeded,
        *(
            cliff_calculation(
                SimulationStatus.FAILED,
                simulation_run_id=run_id,
                created_at=CALCULATED_AT + timedelta(hours=1),
            )
            for run_id in (baseline_run_id, reform_run_id)
        ),
    )

    with sessions() as session:
        rows = result_reads.read_cliff_calculations(
            session,
            baseline_simulation_run_id=baseline_run_id,
            reform_simulation_run_id=reform_run_id,
        )

    assert rows.baseline is not None
    assert rows.baseline.id == running.id
    assert rows.reform is not None
    assert rows.reform.id == succeeded.id


def test_a_side_with_only_failed_calculations_reads_the_newest(
    sessions: sessionmaker[Session],
) -> None:
    run_id = uuid4()
    failures = [
        cliff_calculation(
            SimulationStatus.FAILED,
            simulation_run_id=run_id,
            created_at=CALCULATED_AT + timedelta(minutes=minutes),
        )
        for minutes in (0, 20, 10)
    ]
    store_calculations(sessions, *failures)

    with sessions() as session:
        rows = result_reads.read_cliff_calculations(
            session, baseline_simulation_run_id=run_id, reform_simulation_run_id=uuid4()
        )

    assert rows.baseline is not None
    assert rows.baseline.id == failures[1].id
    assert rows.reform is None


def test_another_runs_calculations_are_not_read(
    sessions: sessionmaker[Session],
) -> None:
    store_calculations(sessions, cliff_calculation(SimulationStatus.SUCCEEDED))

    with sessions() as session:
        rows = result_reads.read_cliff_calculations(
            session,
            baseline_simulation_run_id=uuid4(),
            reform_simulation_run_id=uuid4(),
        )

    assert rows == ReportRunCliffRows(baseline=None, reform=None)


def test_one_run_on_both_sides_reads_its_calculation_for_each(
    sessions: sessionmaker[Session],
) -> None:
    run_id = uuid4()
    succeeded = cliff_calculation(SimulationStatus.SUCCEEDED, simulation_run_id=run_id)
    store_calculations(sessions, succeeded)

    with sessions() as session:
        rows = result_reads.read_cliff_calculations(
            session, baseline_simulation_run_id=run_id, reform_simulation_run_id=run_id
        )

    assert rows.baseline is not None
    assert rows.baseline.id == succeeded.id
    assert rows.reform is rows.baseline
