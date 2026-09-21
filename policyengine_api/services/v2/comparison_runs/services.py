"""Application services for temporary Stage 12 comparison-run persistence."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import Session

from policyengine_api.services.v2.comparison_runs.database_connectors.creates import (
    create_comparison_report,
    create_comparison_simulation,
)
from policyengine_api.services.v2.comparison_runs.database_connectors.reads import (
    read_comparison_report,
    read_comparison_report_by_identity,
    read_comparison_simulation,
    read_comparison_simulation_by_identity,
    read_comparison_simulations_for_report,
)
from policyengine_api.services.v2.comparison_runs.database_connectors.updates import (
    attach_simulation_invocation,
    update_comparison_report,
    update_comparison_simulation,
    update_report_result_comparison,
)
from policyengine_api.services.v2.comparison_runs.database_session import (
    ComparisonRunDatabaseSession,
)
from policyengine_api.services.v2.comparison_runs.transformations import (
    report_record,
    simulation_record,
)
from policyengine_api.services.v2.comparison_runs.types import (
    ComparisonRunLifecycleStatus,
    ComparisonReportPersistenceResult,
    ComparisonReportRecord,
    ComparisonSimulationPersistenceResult,
    ComparisonSimulationRecord,
)
from policyengine_api.services.v2.comparison_runs.validators import (
    ComparisonRunIdentityError,
    ComparisonRunNotFoundError,
    require_aggregation_transition,
    require_comparison_update_only,
    require_lifecycle_transition,
    require_report_conflict_matches,
    require_report_identity,
    require_result_comparison_transition,
    require_result_comparison_unchanged,
    require_simulation_conflict_matches,
    require_simulation_identity,
    require_simulation_parent_matches,
    require_successful_report_replay,
    require_successful_simulation_replay,
)


def create_or_resolve_report(
    session: Session,
    record: ComparisonReportRecord,
) -> ComparisonReportPersistenceResult:
    created_id = create_comparison_report(session, record)
    if created_id is not None:
        row = read_comparison_report(session, created_id, lock=False)
        if row is None:
            raise ComparisonRunIdentityError(
                "created comparison report could not be reloaded"
            )
        return ComparisonReportPersistenceResult(
            record=report_record(row),
            created=True,
        )
    row = read_comparison_report_by_identity(session, record)
    if row is None:
        raise ComparisonRunIdentityError(
            "comparison report conflict did not resolve to an existing identity"
        )
    existing = report_record(row)
    require_report_conflict_matches(existing, record)
    return ComparisonReportPersistenceResult(record=existing, created=False)


def create_or_resolve_simulation(
    session: Session,
    record: ComparisonSimulationRecord,
) -> ComparisonSimulationPersistenceResult:
    parent_row = read_comparison_report(session, record.evaluation_id, lock=False)
    if parent_row is None:
        raise ComparisonRunNotFoundError(
            f"comparison report {record.evaluation_id} does not exist"
        )
    require_simulation_parent_matches(report_record(parent_row), record)
    created_id = create_comparison_simulation(session, record)
    if created_id is not None:
        row = read_comparison_simulation(session, created_id, lock=False)
        if row is None:
            raise ComparisonRunIdentityError(
                "created comparison simulation could not be reloaded"
            )
        return ComparisonSimulationPersistenceResult(
            record=simulation_record(row),
            created=True,
        )
    row = read_comparison_simulation_by_identity(session, record)
    if row is None:
        raise ComparisonRunIdentityError(
            "comparison simulation conflict did not resolve to an existing identity"
        )
    existing = simulation_record(row)
    require_simulation_conflict_matches(existing, record)
    return ComparisonSimulationPersistenceResult(record=existing, created=False)


def replace_report_lifecycle(
    session: Session,
    record: ComparisonReportRecord,
) -> ComparisonReportRecord:
    row = read_comparison_report(session, record.evaluation_id, lock=True)
    if row is None:
        raise ComparisonRunNotFoundError(
            f"comparison report {record.evaluation_id} does not exist"
        )
    existing = report_record(row)
    require_report_identity(existing, record)
    require_result_comparison_unchanged(existing, record)
    require_lifecycle_transition(existing.status, record.status)
    require_aggregation_transition(
        existing.aggregation_status,
        record.aggregation_status,
    )
    if existing.status is ComparisonRunLifecycleStatus.SUCCEEDED:
        require_successful_report_replay(existing, record)
        return existing
    return report_record(update_comparison_report(session, row, record))


def replace_report_result_comparison(
    session: Session,
    record: ComparisonReportRecord,
) -> ComparisonReportRecord:
    row = read_comparison_report(session, record.evaluation_id, lock=True)
    if row is None:
        raise ComparisonRunNotFoundError(
            f"comparison report {record.evaluation_id} does not exist"
        )
    existing = report_record(row)
    require_comparison_update_only(existing, record)
    require_result_comparison_transition(
        existing.comparison_status,
        record.comparison_status,
    )
    if existing.comparison_status in {
        existing.comparison_status.MATCHED,
        existing.comparison_status.DIFFERENT,
    }:
        require_result_comparison_unchanged(existing, record)
        return existing
    return report_record(update_report_result_comparison(session, row, record))


def replace_simulation_lifecycle(
    session: Session,
    record: ComparisonSimulationRecord,
) -> ComparisonSimulationRecord:
    row = read_comparison_simulation(
        session,
        record.simulation_execution_id,
        lock=True,
    )
    if row is None:
        raise ComparisonRunNotFoundError(
            f"comparison simulation {record.simulation_execution_id} does not exist"
        )
    existing = simulation_record(row)
    require_simulation_identity(existing, record)
    require_lifecycle_transition(existing.status, record.status)
    if existing.status is ComparisonRunLifecycleStatus.SUCCEEDED:
        require_successful_simulation_replay(existing, record)
        return existing
    return simulation_record(update_comparison_simulation(session, row, record))


class V2ComparisonRunService:
    def __init__(self, database_session: ComparisonRunDatabaseSession) -> None:
        self._database_session = database_session

    def create_or_resolve_report(
        self,
        record: ComparisonReportRecord,
    ) -> ComparisonReportPersistenceResult:
        with self._database_session.transaction() as session:
            return create_or_resolve_report(session, record)

    def create_or_resolve_simulation(
        self,
        record: ComparisonSimulationRecord,
    ) -> ComparisonSimulationPersistenceResult:
        with self._database_session.transaction() as session:
            return create_or_resolve_simulation(session, record)

    def replace_report_lifecycle(
        self,
        record: ComparisonReportRecord,
    ) -> ComparisonReportRecord:
        with self._database_session.transaction() as session:
            return replace_report_lifecycle(session, record)

    def replace_simulation_lifecycle(
        self,
        record: ComparisonSimulationRecord,
    ) -> ComparisonSimulationRecord:
        with self._database_session.transaction() as session:
            return replace_simulation_lifecycle(session, record)

    def replace_report_result_comparison(
        self,
        record: ComparisonReportRecord,
    ) -> ComparisonReportRecord:
        with self._database_session.transaction() as session:
            return replace_report_result_comparison(session, record)

    def get_report(self, evaluation_id: UUID) -> ComparisonReportRecord:
        with self._database_session.read() as session:
            row = read_comparison_report(session, evaluation_id, lock=False)
            if row is None:
                raise ComparisonRunNotFoundError(
                    f"comparison report {evaluation_id} does not exist"
                )
            return report_record(row)

    def get_simulation(
        self,
        simulation_execution_id: UUID,
    ) -> ComparisonSimulationRecord:
        with self._database_session.read() as session:
            row = read_comparison_simulation(
                session,
                simulation_execution_id,
                lock=False,
            )
            if row is None:
                raise ComparisonRunNotFoundError(
                    f"comparison simulation {simulation_execution_id} does not exist"
                )
            return simulation_record(row)

    def list_simulations(
        self,
        evaluation_id: UUID,
    ) -> tuple[ComparisonSimulationRecord, ...]:
        with self._database_session.read() as session:
            return tuple(
                simulation_record(row)
                for row in read_comparison_simulations_for_report(
                    session,
                    evaluation_id,
                )
            )

    def attach_simulation_invocation(
        self,
        *,
        simulation_execution_id: UUID,
        expected_placeholder: str,
        modal_invocation_id: str,
        updated_at: datetime,
    ) -> ComparisonSimulationRecord:
        with self._database_session.transaction() as session:
            attached_id = attach_simulation_invocation(
                session,
                simulation_execution_id=simulation_execution_id,
                expected_placeholder=expected_placeholder,
                modal_invocation_id=modal_invocation_id,
                updated_at=updated_at,
            )
            row = read_comparison_simulation(
                session,
                attached_id or simulation_execution_id,
                lock=False,
            )
            if row is None:
                raise ComparisonRunNotFoundError(
                    f"comparison simulation {simulation_execution_id} does not exist"
                )
            record = simulation_record(row)
            if record.modal_invocation_id != modal_invocation_id:
                raise ComparisonRunIdentityError(
                    "comparison simulation invocation identity changed"
                )
            return record
