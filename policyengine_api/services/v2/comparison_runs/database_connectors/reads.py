"""Database reads for temporary Stage 12 comparison-run records."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import Session, select

from policyengine_api.data.v2.models import (
    Stage12ComparisonReport,
    Stage12ComparisonSimulation,
)

if TYPE_CHECKING:
    from uuid import UUID

    from policyengine_api.services.v2.comparison_runs.types import (
        ComparisonReportRecord,
        ComparisonSimulationRecord,
    )


def read_comparison_report(
    session: Session,
    evaluation_id: UUID,
    *,
    lock: bool,
) -> Stage12ComparisonReport | None:
    """Return the report row for evaluation_id, or None.

    With lock=True the row is read FOR UPDATE until the transaction ends.
    """
    statement = select(Stage12ComparisonReport).where(
        Stage12ComparisonReport.evaluation_id == evaluation_id
    )
    if lock:
        statement = statement.with_for_update()
    return session.exec(statement).one_or_none()


def read_comparison_report_by_identity(
    session: Session,
    record: ComparisonReportRecord,
) -> Stage12ComparisonReport | None:
    """Return the report row with the record's identity, or None.

    The identity is the environment, calculation flow, production identity,
    worker version and version-manifest digest.
    """
    return session.exec(
        select(Stage12ComparisonReport).where(
            Stage12ComparisonReport.environment == record.environment,
            Stage12ComparisonReport.calculation_flow == record.calculation_flow,
            Stage12ComparisonReport.production_identity == record.production_identity,
            Stage12ComparisonReport.worker_version == record.worker_version,
            Stage12ComparisonReport.version_manifest_sha256
            == record.version_manifest_sha256,
        )
    ).one_or_none()


def read_comparison_simulation(
    session: Session,
    simulation_execution_id: UUID,
    *,
    lock: bool,
) -> Stage12ComparisonSimulation | None:
    """Return the simulation row for simulation_execution_id, or None.

    With lock=True the row is read FOR UPDATE until the transaction ends.
    """
    statement = select(Stage12ComparisonSimulation).where(
        Stage12ComparisonSimulation.simulation_execution_id == simulation_execution_id
    )
    if lock:
        statement = statement.with_for_update()
    return session.exec(statement).one_or_none()


def read_comparison_simulation_by_identity(
    session: Session,
    record: ComparisonSimulationRecord,
) -> Stage12ComparisonSimulation | None:
    """Return the simulation row with the record's identity, or None.

    The identity is the parent evaluation, role, input digest, worker version
    and version-manifest digest.
    """
    return session.exec(
        select(Stage12ComparisonSimulation).where(
            Stage12ComparisonSimulation.evaluation_id == record.evaluation_id,
            Stage12ComparisonSimulation.role == record.role.value,
            Stage12ComparisonSimulation.input_sha256 == record.input_sha256,
            Stage12ComparisonSimulation.worker_version == record.worker_version,
            Stage12ComparisonSimulation.version_manifest_sha256
            == record.version_manifest_sha256,
        )
    ).one_or_none()
