"""Application services for temporary Stage 12 evaluation persistence."""

from __future__ import annotations

from uuid import UUID

from sqlmodel import Session

from policyengine_api.services.v2.evaluation_executions.database_connectors.creates import (
    create_evaluation_report,
    create_evaluation_simulation,
)
from policyengine_api.services.v2.evaluation_executions.database_connectors.reads import (
    read_evaluation_report,
    read_evaluation_report_by_identity,
    read_evaluation_simulation,
    read_evaluation_simulation_by_identity,
)
from policyengine_api.services.v2.evaluation_executions.database_connectors.updates import (
    update_evaluation_report,
    update_evaluation_simulation,
)
from policyengine_api.services.v2.evaluation_executions.database_session import (
    EvaluationExecutionDatabaseSession,
)
from policyengine_api.services.v2.evaluation_executions.transformations import (
    report_record,
    simulation_record,
)
from policyengine_api.services.v2.evaluation_executions.types import (
    EvaluationLifecycleStatus,
    EvaluationReportPersistenceResult,
    EvaluationReportRecord,
    EvaluationSimulationPersistenceResult,
    EvaluationSimulationRecord,
)
from policyengine_api.services.v2.evaluation_executions.validators import (
    EvaluationRecordIdentityError,
    EvaluationRecordNotFoundError,
    require_aggregation_transition,
    require_lifecycle_transition,
    require_report_conflict_matches,
    require_report_identity,
    require_simulation_conflict_matches,
    require_simulation_identity,
    require_simulation_parent_matches,
    require_successful_report_replay,
    require_successful_simulation_replay,
)


def create_or_resolve_report(
    session: Session,
    record: EvaluationReportRecord,
) -> EvaluationReportPersistenceResult:
    created_id = create_evaluation_report(session, record)
    if created_id is not None:
        row = read_evaluation_report(session, created_id, lock=False)
        if row is None:
            raise EvaluationRecordIdentityError(
                "created evaluation report could not be reloaded"
            )
        return EvaluationReportPersistenceResult(
            record=report_record(row),
            created=True,
        )
    row = read_evaluation_report_by_identity(session, record)
    if row is None:
        raise EvaluationRecordIdentityError(
            "evaluation report conflict did not resolve to an existing identity"
        )
    existing = report_record(row)
    require_report_conflict_matches(existing, record)
    return EvaluationReportPersistenceResult(record=existing, created=False)


def create_or_resolve_simulation(
    session: Session,
    record: EvaluationSimulationRecord,
) -> EvaluationSimulationPersistenceResult:
    parent_row = read_evaluation_report(session, record.evaluation_id, lock=False)
    if parent_row is None:
        raise EvaluationRecordNotFoundError(
            f"evaluation report {record.evaluation_id} does not exist"
        )
    require_simulation_parent_matches(report_record(parent_row), record)
    created_id = create_evaluation_simulation(session, record)
    if created_id is not None:
        row = read_evaluation_simulation(session, created_id, lock=False)
        if row is None:
            raise EvaluationRecordIdentityError(
                "created evaluation simulation could not be reloaded"
            )
        return EvaluationSimulationPersistenceResult(
            record=simulation_record(row),
            created=True,
        )
    row = read_evaluation_simulation_by_identity(session, record)
    if row is None:
        raise EvaluationRecordIdentityError(
            "evaluation simulation conflict did not resolve to an existing identity"
        )
    existing = simulation_record(row)
    require_simulation_conflict_matches(existing, record)
    return EvaluationSimulationPersistenceResult(record=existing, created=False)


def replace_report_lifecycle(
    session: Session,
    record: EvaluationReportRecord,
) -> EvaluationReportRecord:
    row = read_evaluation_report(session, record.evaluation_id, lock=True)
    if row is None:
        raise EvaluationRecordNotFoundError(
            f"evaluation report {record.evaluation_id} does not exist"
        )
    existing = report_record(row)
    require_report_identity(existing, record)
    require_lifecycle_transition(existing.status, record.status)
    require_aggregation_transition(
        existing.aggregation_status,
        record.aggregation_status,
    )
    if existing.status is EvaluationLifecycleStatus.SUCCEEDED:
        require_successful_report_replay(existing, record)
        return existing
    return report_record(update_evaluation_report(session, row, record))


def replace_simulation_lifecycle(
    session: Session,
    record: EvaluationSimulationRecord,
) -> EvaluationSimulationRecord:
    row = read_evaluation_simulation(
        session,
        record.simulation_execution_id,
        lock=True,
    )
    if row is None:
        raise EvaluationRecordNotFoundError(
            f"evaluation simulation {record.simulation_execution_id} does not exist"
        )
    existing = simulation_record(row)
    require_simulation_identity(existing, record)
    require_lifecycle_transition(existing.status, record.status)
    if existing.status is EvaluationLifecycleStatus.SUCCEEDED:
        require_successful_simulation_replay(existing, record)
        return existing
    return simulation_record(update_evaluation_simulation(session, row, record))


class V2EvaluationExecutionService:
    def __init__(self, database_session: EvaluationExecutionDatabaseSession) -> None:
        self._database_session = database_session

    def create_or_resolve_report(
        self,
        record: EvaluationReportRecord,
    ) -> EvaluationReportPersistenceResult:
        with self._database_session.transaction() as session:
            return create_or_resolve_report(session, record)

    def create_or_resolve_simulation(
        self,
        record: EvaluationSimulationRecord,
    ) -> EvaluationSimulationPersistenceResult:
        with self._database_session.transaction() as session:
            return create_or_resolve_simulation(session, record)

    def replace_report_lifecycle(
        self,
        record: EvaluationReportRecord,
    ) -> EvaluationReportRecord:
        with self._database_session.transaction() as session:
            return replace_report_lifecycle(session, record)

    def replace_simulation_lifecycle(
        self,
        record: EvaluationSimulationRecord,
    ) -> EvaluationSimulationRecord:
        with self._database_session.transaction() as session:
            return replace_simulation_lifecycle(session, record)

    def get_report(self, evaluation_id: UUID) -> EvaluationReportRecord:
        with self._database_session.read() as session:
            row = read_evaluation_report(session, evaluation_id, lock=False)
            if row is None:
                raise EvaluationRecordNotFoundError(
                    f"evaluation report {evaluation_id} does not exist"
                )
            return report_record(row)
