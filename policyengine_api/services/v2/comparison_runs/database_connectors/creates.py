"""Conflict-safe inserts for temporary Stage 12 comparison-run records."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, col

from policyengine_api.data.v2.models import (
    Stage12ComparisonReport,
    Stage12ComparisonSimulation,
)
from policyengine_api.services.v2.comparison_runs.transformations import (
    report_insert_values,
    simulation_insert_values,
)
from policyengine_api.services.v2.comparison_runs.types import (
    ComparisonReportRecord,
    ComparisonSimulationRecord,
)


def create_comparison_report(
    session: Session,
    record: ComparisonReportRecord,
) -> UUID | None:
    statement = (
        insert(Stage12ComparisonReport)
        .values(**report_insert_values(record))
        .on_conflict_do_nothing(constraint="uq_stage12_eval_reports_identity")
        .returning(col(Stage12ComparisonReport.evaluation_id))
    )
    return session.execute(statement).scalar_one_or_none()


def create_comparison_simulation(
    session: Session,
    record: ComparisonSimulationRecord,
) -> UUID | None:
    statement = (
        insert(Stage12ComparisonSimulation)
        .values(**simulation_insert_values(record))
        .on_conflict_do_nothing(constraint="uq_stage12_eval_simulations_identity")
        .returning(col(Stage12ComparisonSimulation.simulation_execution_id))
    )
    return session.execute(statement).scalar_one_or_none()
