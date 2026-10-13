"""Application services for temporary Stage 12 comparison-run persistence."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.comparison_runs.database_connectors.creates import (
    create_comparison_report,
    create_comparison_simulation,
)
from policyengine_api.services.v2.comparison_runs.database_connectors.reads import (
    read_comparison_report,
    read_comparison_report_by_identity,
    read_comparison_simulation,
    read_comparison_simulation_by_identity,
)
from policyengine_api.services.v2.comparison_runs.database_connectors.updates import (
    update_comparison_report,
    update_comparison_simulation,
    update_report_result_comparison,
)
from policyengine_api.services.v2.comparison_runs.transformations import (
    report_record,
    simulation_record,
)
from policyengine_api.services.v2.comparison_runs.types import (
    ComparisonReportPersistenceResult,
    ComparisonReportRecord,
    ComparisonRunLifecycleStatus,
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

if TYPE_CHECKING:
    from uuid import UUID

    from sqlmodel import Session

    from policyengine_api.services.v2.comparison_runs.database_session import (
        ComparisonRunDatabaseSession,
    )


def create_or_resolve_report(
    session: Session,
    record: ComparisonReportRecord,
) -> ComparisonReportPersistenceResult:
    """Insert a report row, or resolve the existing row with the same identity.

    Raise ComparisonRunIdentityError when an existing row disagrees with the
    record on its release or data identity, so a retry cannot reinterpret it.
    """
    created_id = create_comparison_report(session, record)
    if created_id is not None:
        row = read_comparison_report(session, created_id, lock=False)
        if row is None:
            msg = "created comparison report could not be reloaded"
            raise ComparisonRunIdentityError(msg)
        return ComparisonReportPersistenceResult(
            record=report_record(row),
            created=True,
        )
    row = read_comparison_report_by_identity(session, record)
    if row is None:
        msg = "comparison report conflict did not resolve to an existing identity"
        raise ComparisonRunIdentityError(msg)
    existing = report_record(row)
    require_report_conflict_matches(existing, record)
    return ComparisonReportPersistenceResult(record=existing, created=False)


def create_or_resolve_simulation(
    session: Session,
    record: ComparisonSimulationRecord,
) -> ComparisonSimulationPersistenceResult:
    """Insert a simulation row under its report, or resolve the existing row.

    Raise ComparisonRunNotFoundError when the parent report is missing, and
    ComparisonRunIdentityError when the record disagrees with its parent's
    release and retention fields or with an existing row of the same identity.
    """
    parent_row = read_comparison_report(session, record.evaluation_id, lock=False)
    if parent_row is None:
        msg = f"comparison report {record.evaluation_id} does not exist"
        raise ComparisonRunNotFoundError(msg)
    require_simulation_parent_matches(report_record(parent_row), record)
    created_id = create_comparison_simulation(session, record)
    if created_id is not None:
        row = read_comparison_simulation(session, created_id, lock=False)
        if row is None:
            msg = "created comparison simulation could not be reloaded"
            raise ComparisonRunIdentityError(msg)
        return ComparisonSimulationPersistenceResult(
            record=simulation_record(row),
            created=True,
        )
    row = read_comparison_simulation_by_identity(session, record)
    if row is None:
        msg = "comparison simulation conflict did not resolve to an existing identity"
        raise ComparisonRunIdentityError(msg)
    existing = simulation_record(row)
    require_simulation_conflict_matches(existing, record)
    return ComparisonSimulationPersistenceResult(record=existing, created=False)


def replace_report_lifecycle(
    session: Session,
    record: ComparisonReportRecord,
) -> ComparisonReportRecord:
    """Write a report's new lifecycle, aggregation and output fields under a row lock.

    Identity and result-comparison fields must be unchanged and both status moves
    allowed. A replay against a succeeded report must match it exactly, and then
    returns the stored record without writing.
    """
    row = read_comparison_report(session, record.evaluation_id, lock=True)
    if row is None:
        msg = f"comparison report {record.evaluation_id} does not exist"
        raise ComparisonRunNotFoundError(msg)
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
    """Write a report's result-comparison outcome under a row lock.

    Only the comparison fields and updated_at may differ from the stored row. Once
    the comparison is matched or different, an identical replay returns the
    stored record without writing and any change raises.
    """
    row = read_comparison_report(session, record.evaluation_id, lock=True)
    if row is None:
        msg = f"comparison report {record.evaluation_id} does not exist"
        raise ComparisonRunNotFoundError(msg)
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
    """Write a simulation's new lifecycle and output fields under a row lock.

    Identity fields must be unchanged and the status move allowed. A replay
    against a succeeded simulation must match it exactly, and then returns the
    stored record without writing.
    """
    row = read_comparison_simulation(
        session,
        record.simulation_execution_id,
        lock=True,
    )
    if row is None:
        msg = f"comparison simulation {record.simulation_execution_id} does not exist"
        raise ComparisonRunNotFoundError(msg)
    existing = simulation_record(row)
    require_simulation_identity(existing, record)
    require_lifecycle_transition(existing.status, record.status)
    if existing.status is ComparisonRunLifecycleStatus.SUCCEEDED:
        require_successful_simulation_replay(existing, record)
        return existing
    return simulation_record(update_comparison_simulation(session, row, record))


class V2ComparisonRunService:
    """Comparison-run operations, each run in its own database transaction."""

    def __init__(self, database_session: ComparisonRunDatabaseSession) -> None:
        """Open a new session from database_session for every call."""
        self._database_session = database_session

    def create_or_resolve_report(
        self,
        record: ComparisonReportRecord,
    ) -> ComparisonReportPersistenceResult:
        """Insert a report row or resolve its existing identity, in one transaction."""
        with self._database_session.transaction() as session:
            return create_or_resolve_report(session, record)

    def create_or_resolve_simulation(
        self,
        record: ComparisonSimulationRecord,
    ) -> ComparisonSimulationPersistenceResult:
        """Insert a simulation row or resolve its identity, in one transaction."""
        with self._database_session.transaction() as session:
            return create_or_resolve_simulation(session, record)

    def replace_report_lifecycle(
        self,
        record: ComparisonReportRecord,
    ) -> ComparisonReportRecord:
        """Write a report's lifecycle update in one transaction, under a row lock."""
        with self._database_session.transaction() as session:
            return replace_report_lifecycle(session, record)

    def replace_simulation_lifecycle(
        self,
        record: ComparisonSimulationRecord,
    ) -> ComparisonSimulationRecord:
        """Write a simulation lifecycle update in one transaction, under a row lock."""
        with self._database_session.transaction() as session:
            return replace_simulation_lifecycle(session, record)

    def replace_report_result_comparison(
        self,
        record: ComparisonReportRecord,
    ) -> ComparisonReportRecord:
        """Write a report's result-comparison outcome in one transaction."""
        with self._database_session.transaction() as session:
            return replace_report_result_comparison(session, record)

    def get_report(self, evaluation_id: UUID) -> ComparisonReportRecord:
        """Return the stored report, or raise ComparisonRunNotFoundError."""
        with self._database_session.read() as session:
            row = read_comparison_report(session, evaluation_id, lock=False)
            if row is None:
                msg = f"comparison report {evaluation_id} does not exist"
                raise ComparisonRunNotFoundError(msg)
            return report_record(row)
