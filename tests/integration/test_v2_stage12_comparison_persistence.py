"""PostgreSQL tests for comparison-run persistence as the Stage 12 role.

The simulation API and its Modal worker write the temporary Stage 12 tables as
``policyengine_stage12_<environment>``. These tests run the comparison-run
services as that role in the disposable database, so a statement its declared
privileges don't allow fails here (rule
``api.v2.runtime-privileges-tested-as-runtime-role``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session

from policyengine_api.data.v2.models import (
    Stage12ComparisonReport,
    Stage12ComparisonSimulation,
    User,
)
from policyengine_api.services.v2.comparison_runs.database_session import (
    ComparisonRunDatabaseSession,
)
from policyengine_api.services.v2.comparison_runs.services import (
    V2ComparisonRunService,
)
from policyengine_api.services.v2.comparison_runs.types import (
    ComparisonRunLifecycleStatus,
)
from tests.unit.v2.comparison_run_support import (
    comparison_report_record,
    comparison_simulation_record,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from policyengine_api.services.v2.comparison_runs.types import (
        ComparisonReportRecord,
        ComparisonSimulationRecord,
    )


@pytest.fixture
def stage12_sessions(
    disposable_v2_database_url, managed_v2_roles, v2_engine_as_role
) -> Iterator[sessionmaker[Session]]:
    """Open sessions as the Stage 12 role; remove this test's rows as the superuser."""
    stage12_engine = v2_engine_as_role(managed_v2_roles.stage12)
    cleanup_engine = create_engine(disposable_v2_database_url)
    factory = sessionmaker(stage12_engine, class_=Session, expire_on_commit=False)
    factory.kw["info"] = {"evaluation_ids": []}
    try:
        yield factory
    finally:
        evaluation_ids = factory.kw["info"]["evaluation_ids"]
        if evaluation_ids:
            with cleanup_engine.begin() as connection:
                connection.execute(
                    delete(Stage12ComparisonSimulation).where(
                        Stage12ComparisonSimulation.evaluation_id.in_(evaluation_ids)
                    )
                )
                connection.execute(
                    delete(Stage12ComparisonReport).where(
                        Stage12ComparisonReport.evaluation_id.in_(evaluation_ids)
                    )
                )
        stage12_engine.dispose()
        cleanup_engine.dispose()


def _new_report(stage12_sessions) -> ComparisonReportRecord:
    """Return a report record with a fresh identity the fixture removes afterwards."""
    created_at = datetime.now(UTC)
    evaluation_id = uuid4()
    stage12_sessions.kw["info"]["evaluation_ids"].append(evaluation_id)
    return comparison_report_record(
        evaluation_id=evaluation_id,
        production_identity=f"production-job-{evaluation_id.hex[:12]}",
        incumbent_execution_id=f"production-job-{evaluation_id.hex[:12]}",
        created_at=created_at,
        updated_at=created_at,
        retention_expires_at=created_at + timedelta(days=30),
    )


def _baseline_simulation(report: ComparisonReportRecord) -> ComparisonSimulationRecord:
    return comparison_simulation_record(
        simulation_execution_id=uuid4(),
        evaluation_id=report.evaluation_id,
        created_at=report.created_at,
        updated_at=report.created_at,
        retention_expires_at=report.retention_expires_at,
    )


def test_stage12_sessions_act_as_the_stage12_role(
    stage12_sessions, managed_v2_roles
) -> None:
    with stage12_sessions() as session:
        current_role = session.execute(select(func.current_user())).scalar_one()

    assert current_role == managed_v2_roles.stage12


def test_stage12_role_creates_and_resolves_reports_and_simulations(
    stage12_sessions,
) -> None:
    service = V2ComparisonRunService(ComparisonRunDatabaseSession(stage12_sessions))
    report = _new_report(stage12_sessions)
    simulation = _baseline_simulation(report)

    created_report = service.create_or_resolve_report(report)
    retried_report = service.create_or_resolve_report(report)
    created_simulation = service.create_or_resolve_simulation(simulation)
    retried_simulation = service.create_or_resolve_simulation(simulation)

    assert (created_report.created, retried_report.created) == (True, False)
    assert retried_report.record.evaluation_id == report.evaluation_id
    assert (created_simulation.created, retried_simulation.created) == (True, False)
    assert service.get_report(report.evaluation_id).status is (
        ComparisonRunLifecycleStatus.PENDING
    )


def test_stage12_role_updates_lifecycles_under_row_locks(stage12_sessions) -> None:
    service = V2ComparisonRunService(ComparisonRunDatabaseSession(stage12_sessions))
    report = _new_report(stage12_sessions)
    simulation = _baseline_simulation(report)
    service.create_or_resolve_report(report)
    service.create_or_resolve_simulation(simulation)
    started_at = datetime.now(UTC)

    running_report = service.replace_report_lifecycle(
        type(report).model_validate(
            {**report.model_dump(), "status": "running", "updated_at": started_at}
        )
    )
    running_simulation = service.replace_simulation_lifecycle(
        type(simulation).model_validate(
            {**simulation.model_dump(), "status": "running", "updated_at": started_at}
        )
    )

    assert running_report.status is ComparisonRunLifecycleStatus.RUNNING
    assert running_simulation.status is ComparisonRunLifecycleStatus.RUNNING
    assert service.get_report(report.evaluation_id).status is (
        ComparisonRunLifecycleStatus.RUNNING
    )


def test_stage12_role_cannot_read_tables_outside_its_declared_privileges(
    stage12_sessions,
) -> None:
    with stage12_sessions() as session, pytest.raises(ProgrammingError) as refusal:
        session.execute(select(func.count()).select_from(User)).scalar_one()

    assert "permission denied for table users" in str(refusal.value)
