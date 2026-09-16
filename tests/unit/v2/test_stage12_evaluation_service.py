"""Service and SQL statement tests for temporary evaluation persistence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from uuid import UUID, uuid4

from sqlalchemy.dialects import postgresql
import pytest

from policyengine_api.data.v2.models import (
    Stage12EvaluationReport,
    Stage12EvaluationSimulation,
)
from policyengine_api.services.v2.evaluation_executions import services
from policyengine_api.services.v2.evaluation_executions.database_connectors import (
    creates,
)
from policyengine_api.services.v2.evaluation_executions.transformations import (
    report_insert_values,
    report_record,
    simulation_insert_values,
    simulation_record,
)
from policyengine_api.services.v2.evaluation_executions.types import (
    EvaluationReportRecord,
    EvaluationSimulationRecord,
)
from policyengine_api.services.v2.evaluation_executions.validators import (
    EvaluationRecordIdentityError,
    EvaluationStateTransitionError,
    require_aggregation_transition,
    require_lifecycle_transition,
    require_report_identity,
)

NOW = datetime(2026, 9, 14, tzinfo=timezone.utc)
EVALUATION_ID = UUID("00000000-0000-4000-8000-000000000001")
SIMULATION_ID = UUID("00000000-0000-4000-8000-000000000002")
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def _report(**changes: object) -> EvaluationReportRecord:
    fields: dict[str, object] = {
        "evaluation_id": EVALUATION_ID,
        "status": "pending",
        "aggregation_status": "not_started",
        "environment": "test",
        "calculation_flow": "economy",
        "originating_request_id": "request-1",
        "production_identity": "production-job-1",
        "incumbent_execution_id": "production-job-1",
        "worker_version": "5.2.0",
        "modal_application": "policyengine-v2-worker-5-2-0",
        "report_coordinator_callable": "coordinate_report",
        "version_manifest_sha256": DIGEST_A,
        "policyengine_version": "5.2.0",
        "country_package_name": "policyengine-us",
        "country_package_version": "1.900.0",
        "country": "us",
        "dataset_identity": "populace_us_2024",
        "dataset_uri": "hf://policyengine/populace-us/data.h5@revision",
        "data_package_name": "policyengine-us-data",
        "data_package_version": "1.0.0",
        "data_artifact_revision": "revision",
        "created_at": NOW,
        "updated_at": NOW,
        "retention_expires_at": NOW + timedelta(days=30),
    }
    fields.update(changes)
    return EvaluationReportRecord.model_validate(fields)


def _simulation(**changes: object) -> EvaluationSimulationRecord:
    fields: dict[str, object] = {
        "simulation_execution_id": SIMULATION_ID,
        "evaluation_id": EVALUATION_ID,
        "role": "baseline",
        "input_sha256": DIGEST_B,
        "worker_version": "5.2.0",
        "modal_application": "policyengine-v2-worker-5-2-0",
        "simulation_callable": "run_simulation",
        "version_manifest_sha256": DIGEST_A,
        "status": "pending",
        "created_at": NOW,
        "updated_at": NOW,
        "retention_expires_at": NOW + timedelta(days=30),
    }
    fields.update(changes)
    return EvaluationSimulationRecord.model_validate(fields)


def test_insert_statements_use_the_parent_and_child_identities() -> None:
    report_statement = (
        creates.insert(creates.Stage12EvaluationReport)
        .values(**report_insert_values(_report()))
        .on_conflict_do_nothing(constraint="uq_stage12_eval_reports_identity")
        .returning(creates.Stage12EvaluationReport.evaluation_id)
    )
    simulation_statement = (
        creates.insert(creates.Stage12EvaluationSimulation)
        .values(**simulation_insert_values(_simulation()))
        .on_conflict_do_nothing(constraint="uq_stage12_eval_simulations_identity")
        .returning(creates.Stage12EvaluationSimulation.simulation_execution_id)
    )

    report_sql = str(report_statement.compile(dialect=postgresql.dialect()))
    simulation_sql = str(simulation_statement.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT ON CONSTRAINT uq_stage12_eval_reports_identity" in report_sql
    assert "RETURNING stage12_evaluation_reports.evaluation_id" in report_sql
    assert (
        "ON CONFLICT ON CONSTRAINT uq_stage12_eval_simulations_identity"
        in simulation_sql
    )
    assert (
        "RETURNING stage12_evaluation_simulations.simulation_execution_id"
        in simulation_sql
    )


def test_contract_records_round_trip_through_sqlmodel_rows() -> None:
    report = _report()
    simulation = _simulation()
    report_row = Stage12EvaluationReport(**report_insert_values(report))
    simulation_row = Stage12EvaluationSimulation(**simulation_insert_values(simulation))

    assert report_record(report_row) == report
    assert simulation_record(simulation_row) == simulation


def test_conflicting_report_creation_reuses_the_stored_identity(monkeypatch) -> None:
    stored = _report()
    row = Stage12EvaluationReport(**report_insert_values(stored))
    retried = stored.model_copy(
        update={
            "evaluation_id": uuid4(),
            "originating_request_id": "request-retry",
            "created_at": NOW + timedelta(seconds=1),
            "updated_at": NOW + timedelta(seconds=1),
            "retention_expires_at": NOW + timedelta(days=29),
        }
    )
    monkeypatch.setattr(services, "create_evaluation_report", lambda *_args: None)
    monkeypatch.setattr(
        services,
        "read_evaluation_report_by_identity",
        lambda *_args: row,
    )

    result = services.create_or_resolve_report(Mock(), retried)

    assert result.created is False
    assert result.record.evaluation_id == EVALUATION_ID
    assert result.record.originating_request_id == "request-1"


def test_conflicting_report_creation_rejects_different_bundle_provenance(
    monkeypatch,
) -> None:
    stored = _report()
    row = Stage12EvaluationReport(**report_insert_values(stored))
    candidate = stored.model_copy(update={"country_package_version": "1.901.0"})
    monkeypatch.setattr(services, "create_evaluation_report", lambda *_args: None)
    monkeypatch.setattr(
        services,
        "read_evaluation_report_by_identity",
        lambda *_args: row,
    )

    with pytest.raises(EvaluationRecordIdentityError, match="country_package_version"):
        services.create_or_resolve_report(Mock(), candidate)


def test_matching_successful_child_is_returned_for_a_retry(monkeypatch) -> None:
    stored = _simulation(
        status="succeeded",
        completed_at=NOW + timedelta(minutes=1),
        output_uri="gs://private-stage12/simulations/baseline.parquet",
        output_sha256=DIGEST_A,
        output_schema_version=1,
        row_identity_columns=("household_id",),
        row_count=100,
        row_identity_sha256=DIGEST_B,
    )
    row = Stage12EvaluationSimulation(**simulation_insert_values(stored))
    retried = _simulation(simulation_execution_id=uuid4())
    monkeypatch.setattr(
        services,
        "create_evaluation_simulation",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        services,
        "read_evaluation_simulation_by_identity",
        lambda *_args: row,
    )

    result = services.create_or_resolve_simulation(Mock(), retried)

    assert result.created is False
    assert result.record.status == "succeeded"
    assert result.record.output_sha256 == DIGEST_A


def test_lifecycle_updates_reject_identity_changes_and_state_reversal() -> None:
    pending = _report()
    changed_identity = pending.model_copy(update={"worker_version": "5.3.0"})
    with pytest.raises(EvaluationRecordIdentityError, match="worker_version"):
        require_report_identity(pending, changed_identity)

    require_lifecycle_transition(pending.status, pending.status.RUNNING)
    require_lifecycle_transition(
        pending.status.FAILED,
        pending.status.RUNNING,
    )
    with pytest.raises(EvaluationStateTransitionError, match="succeeded to running"):
        require_lifecycle_transition(
            pending.status.SUCCEEDED,
            pending.status.RUNNING,
        )
    require_aggregation_transition(
        pending.aggregation_status,
        pending.aggregation_status.RUNNING,
    )
    require_aggregation_transition(
        pending.aggregation_status.FAILED,
        pending.aggregation_status.RUNNING,
    )
    with pytest.raises(EvaluationStateTransitionError, match="succeeded to running"):
        require_aggregation_transition(
            pending.aggregation_status.SUCCEEDED,
            pending.aggregation_status.RUNNING,
        )


@pytest.mark.parametrize(
    "record_factory",
    [_report, _simulation],
)
def test_contract_records_require_bounded_timezone_aware_retention(
    record_factory,
) -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        record_factory(retention_expires_at=NOW)
    with pytest.raises(ValueError, match="must not exceed 30 days"):
        record_factory(retention_expires_at=NOW + timedelta(days=30, seconds=1))
    with pytest.raises(ValueError, match="include a timezone"):
        record_factory(
            created_at=NOW.replace(tzinfo=None),
            retention_expires_at=(NOW + timedelta(days=1)).replace(tzinfo=None),
        )
