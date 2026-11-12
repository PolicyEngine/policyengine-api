"""Database reads of v2 simulations and their newest runs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import and_, func, select
from sqlalchemy.orm import aliased
from sqlmodel import col

from policyengine_api.data.v2.models import (
    Dataset,
    Region,
    Simulation,
    SimulationRun,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)
from policyengine_api.services.v2.stored_simulations.types import (
    StoredSimulationRows,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlmodel import Session


def read_simulation_rows(
    session: Session, *, country_id: str, simulation_id: UUID
) -> StoredSimulationRows | None:
    """Return the simulation if it is of the country's model, in one query.

    A simulation has no country column: its catalog version's model is the
    country's (``policyengine-<country>``). It comes with its region's code,
    its dataset's name and its newest run: the run created last (ties broken
    by the larger ID), whatever its year, status and versions.
    """
    run_rank = (
        func.row_number()
        .over(
            partition_by=col(SimulationRun.simulation_id),
            order_by=(
                col(SimulationRun.created_at).desc(),
                col(SimulationRun.id).desc(),
            ),
        )
        .label("newest_first")
    )
    ranked_runs = (
        select(SimulationRun, run_rank)
        .where(col(SimulationRun.simulation_id) == simulation_id)
        .subquery("ranked_simulation_runs")
    )
    newest_run = aliased(SimulationRun, ranked_runs)
    statement = (
        select(Simulation, col(Region.code), col(Dataset.name), newest_run)
        .join(
            TaxBenefitModelVersion,
            col(TaxBenefitModelVersion.id) == Simulation.tax_benefit_model_version_id,
        )
        .join(
            TaxBenefitModel, col(TaxBenefitModel.id) == TaxBenefitModelVersion.model_id
        )
        .outerjoin(Region, col(Region.id) == Simulation.region_id)
        .outerjoin(Dataset, col(Dataset.id) == Simulation.dataset_id)
        .outerjoin(
            newest_run,
            and_(
                col(newest_run.simulation_id) == Simulation.id,
                ranked_runs.c.newest_first == 1,
            ),
        )
        .where(
            col(Simulation.id) == simulation_id,
            col(TaxBenefitModel.name) == f"policyengine-{country_id}",
        )
    )
    row = session.execute(statement).one_or_none()
    if row is None:
        return None
    simulation, region_code, dataset_name, run = row
    return StoredSimulationRows(
        simulation=simulation,
        region_code=region_code,
        dataset_name=dataset_name,
        newest_run=run,
    )
