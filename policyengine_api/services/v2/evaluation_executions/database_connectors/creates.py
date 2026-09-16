"""Conflict-safe inserts for temporary Stage 12 evaluation records."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, col

from policyengine_api.data.v2.models import (
    Stage12EvaluationReport,
    Stage12EvaluationSimulation,
)
from policyengine_api.services.v2.evaluation_executions.transformations import (
    report_insert_values,
    simulation_insert_values,
)
from policyengine_api.services.v2.evaluation_executions.types import (
    EvaluationReportRecord,
    EvaluationSimulationRecord,
)


def create_evaluation_report(
    session: Session,
    record: EvaluationReportRecord,
) -> UUID | None:
    statement = (
        insert(Stage12EvaluationReport)
        .values(**report_insert_values(record))
        .on_conflict_do_nothing(constraint="uq_stage12_eval_reports_identity")
        .returning(col(Stage12EvaluationReport.evaluation_id))
    )
    return session.execute(statement).scalar_one_or_none()


def create_evaluation_simulation(
    session: Session,
    record: EvaluationSimulationRecord,
) -> UUID | None:
    statement = (
        insert(Stage12EvaluationSimulation)
        .values(**simulation_insert_values(record))
        .on_conflict_do_nothing(constraint="uq_stage12_eval_simulations_identity")
        .returning(col(Stage12EvaluationSimulation.simulation_execution_id))
    )
    return session.execute(statement).scalar_one_or_none()
