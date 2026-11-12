"""Database reads of the calculated households a household report run names."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import col, select

from policyengine_api.data.v2.models import SimulationRun
from policyengine_api.services.v2.stored_reports.household_results.types import (
    HouseholdResultRows,
)

if TYPE_CHECKING:
    from sqlmodel import Session

    from policyengine_api.data.v2.models import ReportRun


def read_household_result_rows(
    session: Session, *, report_run: ReportRun
) -> HouseholdResultRows:
    """Return the result documents of the report run's simulation runs, in one query.

    Each simulation run the report run names maps to its ``household_result``;
    a run that does not exist is absent.
    """
    simulation_run_ids = [report_run.baseline_simulation_run_id]
    if report_run.reform_simulation_run_id is not None:
        simulation_run_ids.append(report_run.reform_simulation_run_id)
    statement = select(
        col(SimulationRun.id), col(SimulationRun.household_result)
    ).where(col(SimulationRun.id).in_(simulation_run_ids))
    return HouseholdResultRows(documents=dict(session.exec(statement).all()))
