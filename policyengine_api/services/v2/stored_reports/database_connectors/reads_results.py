"""Database reads of one report run's result rows."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import case
from sqlmodel import col, select

from policyengine_api.data.v2.models import (
    BudgetSummary,
    CliffImpact,
    CongressionalDistrictImpact,
    ConstituencyImpact,
    DecileImpact,
    Inequality,
    IntraDecileImpact,
    LaborSupplyDecileResponse,
    LaborSupplyResponse,
    LocalAuthorityImpact,
    Poverty,
    ProgramStatistics,
    SimulationStatus,
    WithheldAreaCode,
)
from policyengine_api.services.v2.stored_reports.economy_results.types import (
    EconomyResultRows,
    ReportRunCliffRows,
    ReportRunResultColumns,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlmodel import Session

    from policyengine_api.data.v2.models import ReportRun


def _side_cliff_calculation(
    session: Session, simulation_run_id: UUID
) -> CliffImpact | None:
    """Return the run's unfailed cliff calculation, else its newest failed one.

    A run has at most one calculation that hasn't failed
    (``uq_cliff_impacts_unfailed``), so ordering failed ones last reads it
    first; among failed ones, the newest is read, the larger ID breaking a
    tie in creation time.
    """
    return session.exec(
        select(CliffImpact)
        .where(CliffImpact.simulation_run_id == simulation_run_id)
        .order_by(
            case((col(CliffImpact.status) == SimulationStatus.FAILED, 1), else_=0),
            col(CliffImpact.created_at).desc(),
            col(CliffImpact.id).desc(),
        )
        .limit(1)
    ).first()


def read_cliff_calculations(
    session: Session,
    *,
    baseline_simulation_run_id: UUID,
    reform_simulation_run_id: UUID,
) -> ReportRunCliffRows:
    """Return each side's cliff calculation of its simulation run, or None.

    It is the run's calculation that hasn't failed, else its newest failed
    one: one query per distinct run, so a report run naming one simulation
    run on both sides reads it once, for both.
    """
    baseline = _side_cliff_calculation(session, baseline_simulation_run_id)
    reform = (
        baseline
        if reform_simulation_run_id == baseline_simulation_run_id
        else _side_cliff_calculation(session, reform_simulation_run_id)
    )
    return ReportRunCliffRows(baseline=baseline, reform=reform)


def read_economy_result_rows(  # noqa: PLR0913  # the session, then each part of the run the read needs
    session: Session,
    *,
    country_id: str,
    report_run: ReportRun,
    reform_simulation_run_id: UUID,
    on_local_area_dataset: bool,
    cliff_calculations: ReportRunCliffRows,
) -> EconomyResultRows:
    """Return every result row of ``report_run``, one query per result table.

    The comparison tables' rows are the report run's; the poverty and
    inequality rows are those of its baseline and reform simulation runs.
    The withheld area codes are read only for a local-area report's run
    (``on_local_area_dataset``), whose writer records them.
    ``cliff_calculations`` are its simulation runs' cliff calculations, as
    ``read_cliff_calculations`` read them. The report run's own four cliff
    columns are not read.
    """
    report_run_id = report_run.id
    simulation_run_ids = (
        report_run.baseline_simulation_run_id,
        reform_simulation_run_id,
    )
    return EconomyResultRows(
        country_id=country_id,
        report_run=ReportRunResultColumns(
            country_package_version=report_run.country_package_version,
            data_version=report_run.data_version,
            spm_provenance=report_run.spm_provenance,
        ),
        baseline_simulation_run_id=report_run.baseline_simulation_run_id,
        reform_simulation_run_id=reform_simulation_run_id,
        budget_summary=tuple(
            session.exec(
                select(BudgetSummary).where(
                    BudgetSummary.report_run_id == report_run_id
                )
            )
        ),
        program_statistics=tuple(
            session.exec(
                select(ProgramStatistics).where(
                    ProgramStatistics.report_run_id == report_run_id
                )
            )
        ),
        decile_impacts=tuple(
            session.exec(
                select(DecileImpact).where(DecileImpact.report_run_id == report_run_id)
            )
        ),
        intra_decile_impacts=tuple(
            session.exec(
                select(IntraDecileImpact).where(
                    IntraDecileImpact.report_run_id == report_run_id
                )
            )
        ),
        poverty=tuple(
            session.exec(
                select(Poverty).where(
                    col(Poverty.simulation_run_id).in_(simulation_run_ids)
                )
            )
        ),
        inequality=tuple(
            session.exec(
                select(Inequality).where(
                    col(Inequality.simulation_run_id).in_(simulation_run_ids)
                )
            )
        ),
        labor_supply_responses=tuple(
            session.exec(
                select(LaborSupplyResponse).where(
                    LaborSupplyResponse.report_run_id == report_run_id
                )
            )
        ),
        labor_supply_decile_responses=tuple(
            session.exec(
                select(LaborSupplyDecileResponse).where(
                    LaborSupplyDecileResponse.report_run_id == report_run_id
                )
            )
        ),
        congressional_district_impacts=tuple(
            session.exec(
                select(CongressionalDistrictImpact).where(
                    CongressionalDistrictImpact.report_run_id == report_run_id
                )
            )
        ),
        constituency_impacts=tuple(
            session.exec(
                select(ConstituencyImpact).where(
                    ConstituencyImpact.report_run_id == report_run_id
                )
            )
        ),
        local_authority_impacts=tuple(
            session.exec(
                select(LocalAuthorityImpact).where(
                    LocalAuthorityImpact.report_run_id == report_run_id
                )
            )
        ),
        cliff_calculations=cliff_calculations,
        on_local_area_dataset=on_local_area_dataset,
        withheld_area_codes=(
            tuple(
                session.exec(
                    select(WithheldAreaCode).where(
                        WithheldAreaCode.report_run_id == report_run_id
                    )
                )
            )
            if on_local_area_dataset
            else ()
        ),
    )
