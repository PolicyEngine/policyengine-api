"""Database reads for temporary Stage 12 evaluation records."""

from __future__ import annotations

from uuid import UUID

from sqlmodel import Session, select

from policyengine_api.data.v2.models import (
    Stage12EvaluationReport,
    Stage12EvaluationSimulation,
)
from policyengine_api.services.v2.evaluation_executions.types import (
    EvaluationReportRecord,
    EvaluationSimulationRecord,
)


def read_evaluation_report(
    session: Session,
    evaluation_id: UUID,
    *,
    lock: bool,
) -> Stage12EvaluationReport | None:
    statement = select(Stage12EvaluationReport).where(
        Stage12EvaluationReport.evaluation_id == evaluation_id
    )
    if lock:
        statement = statement.with_for_update()
    return session.exec(statement).one_or_none()


def read_evaluation_report_by_identity(
    session: Session,
    record: EvaluationReportRecord,
) -> Stage12EvaluationReport | None:
    return session.exec(
        select(Stage12EvaluationReport).where(
            Stage12EvaluationReport.environment == record.environment,
            Stage12EvaluationReport.calculation_flow == record.calculation_flow,
            Stage12EvaluationReport.production_identity == record.production_identity,
            Stage12EvaluationReport.worker_version == record.worker_version,
            Stage12EvaluationReport.version_manifest_sha256
            == record.version_manifest_sha256,
        )
    ).one_or_none()


def read_evaluation_simulation(
    session: Session,
    simulation_execution_id: UUID,
    *,
    lock: bool,
) -> Stage12EvaluationSimulation | None:
    statement = select(Stage12EvaluationSimulation).where(
        Stage12EvaluationSimulation.simulation_execution_id == simulation_execution_id
    )
    if lock:
        statement = statement.with_for_update()
    return session.exec(statement).one_or_none()


def read_evaluation_simulation_by_identity(
    session: Session,
    record: EvaluationSimulationRecord,
) -> Stage12EvaluationSimulation | None:
    return session.exec(
        select(Stage12EvaluationSimulation).where(
            Stage12EvaluationSimulation.evaluation_id == record.evaluation_id,
            Stage12EvaluationSimulation.role == record.role.value,
            Stage12EvaluationSimulation.input_sha256 == record.input_sha256,
            Stage12EvaluationSimulation.worker_version == record.worker_version,
            Stage12EvaluationSimulation.version_manifest_sha256
            == record.version_manifest_sha256,
        )
    ).one_or_none()
