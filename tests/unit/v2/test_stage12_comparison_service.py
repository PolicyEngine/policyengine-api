"""Service and SQL statement tests for temporary comparison-run persistence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from uuid import UUID, uuid4

from sqlalchemy.dialects import postgresql
import pytest

from policyengine_api.data.v2.models import (
    Stage12ComparisonReport,
    Stage12ComparisonSimulation,
)
from policyengine_api.services.v2.comparison_runs import services
from policyengine_api.services.v2.comparison_runs.database_connectors import (
    creates,
)
from policyengine_api.services.v2.comparison_runs.transformations import (
    report_insert_values,
    report_record,
    simulation_insert_values,
    simulation_record,
)
from policyengine_api.services.v2.comparison_runs.types import (
    ComparisonReportRecord,
    ComparisonSimulationRecord,
    ResultComparisonStatus,
)
from policyengine_api.services.v2.comparison_runs.validators import (
    ComparisonRunIdentityError,
    ComparisonRunStateTransitionError,
    require_aggregation_transition,
    require_lifecycle_transition,
    require_report_identity,
    require_result_comparison_transition,
)

NOW = datetime(2026, 9, 14, tzinfo=timezone.utc)
EVALUATION_ID = UUID("00000000-0000-4000-8000-000000000001")
SIMULATION_ID = UUID("00000000-0000-4000-8000-000000000002")
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def _report(**changes: object) -> ComparisonReportRecord:
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
    return ComparisonReportRecord.model_validate(fields)


def _simulation(**changes: object) -> ComparisonSimulationRecord:
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
    return ComparisonSimulationRecord.model_validate(fields)


def test_insert_statements_use_the_parent_and_child_identities() -> None:
    report_statement = (
        creates.insert(creates.Stage12ComparisonReport)
        .values(**report_insert_values(_report()))
        .on_conflict_do_nothing(constraint="uq_stage12_eval_reports_identity")
        .returning(creates.Stage12ComparisonReport.evaluation_id)
    )
    simulation_statement = (
        creates.insert(creates.Stage12ComparisonSimulation)
        .values(**simulation_insert_values(_simulation()))
        .on_conflict_do_nothing(constraint="uq_stage12_eval_simulations_identity")
        .returning(creates.Stage12ComparisonSimulation.simulation_execution_id)
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
    report_row = Stage12ComparisonReport(**report_insert_values(report))
    simulation_row = Stage12ComparisonSimulation(**simulation_insert_values(simulation))

    assert report_record(report_row) == report
    assert simulation_record(simulation_row) == simulation


def test_conflicting_report_creation_reuses_the_stored_identity(monkeypatch) -> None:
    stored = _report()
    row = Stage12ComparisonReport(**report_insert_values(stored))
    retried = stored.model_copy(
        update={
            "evaluation_id": uuid4(),
            "originating_request_id": "request-retry",
            "created_at": NOW + timedelta(seconds=1),
            "updated_at": NOW + timedelta(seconds=1),
            "retention_expires_at": NOW + timedelta(days=29),
        }
    )
    monkeypatch.setattr(services, "create_comparison_report", lambda *_args: None)
    monkeypatch.setattr(
        services,
        "read_comparison_report_by_identity",
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
    row = Stage12ComparisonReport(**report_insert_values(stored))
    candidate = stored.model_copy(update={"country_package_version": "1.901.0"})
    monkeypatch.setattr(services, "create_comparison_report", lambda *_args: None)
    monkeypatch.setattr(
        services,
        "read_comparison_report_by_identity",
        lambda *_args: row,
    )

    with pytest.raises(ComparisonRunIdentityError, match="country_package_version"):
        services.create_or_resolve_report(Mock(), candidate)


def test_matching_successful_child_is_returned_for_a_retry(monkeypatch) -> None:
    parent_row = Stage12ComparisonReport(**report_insert_values(_report()))
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
    row = Stage12ComparisonSimulation(**simulation_insert_values(stored))
    retried = _simulation(simulation_execution_id=uuid4())
    monkeypatch.setattr(
        services,
        "create_comparison_simulation",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        services,
        "read_comparison_report",
        lambda *_args, **_kwargs: parent_row,
    )
    monkeypatch.setattr(
        services,
        "read_comparison_simulation_by_identity",
        lambda *_args: row,
    )

    result = services.create_or_resolve_simulation(Mock(), retried)

    assert result.created is False
    assert result.record.status == "succeeded"
    assert result.record.output_sha256 == DIGEST_A


@pytest.mark.parametrize(
    ("field_name", "other_value"),
    [
        ("worker_version", "5.3.0"),
        ("modal_application", "different-application"),
        ("version_manifest_sha256", DIGEST_B),
        ("created_at", NOW + timedelta(seconds=1)),
        ("retention_expires_at", NOW + timedelta(days=29)),
    ],
)
def test_child_creation_rejects_parent_provenance_or_retention_mismatch(
    monkeypatch,
    field_name,
    other_value,
) -> None:
    parent_row = Stage12ComparisonReport(**report_insert_values(_report()))
    child = _simulation(**{field_name: other_value})
    create = Mock()
    monkeypatch.setattr(
        services,
        "read_comparison_report",
        lambda *_args, **_kwargs: parent_row,
    )
    monkeypatch.setattr(services, "create_comparison_simulation", create)

    with pytest.raises(ComparisonRunIdentityError, match=field_name):
        services.create_or_resolve_simulation(Mock(), child)

    create.assert_not_called()


def test_child_creation_requires_an_existing_parent(monkeypatch) -> None:
    create = Mock()
    monkeypatch.setattr(
        services,
        "read_comparison_report",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(services, "create_comparison_simulation", create)

    with pytest.raises(LookupError, match="does not exist"):
        services.create_or_resolve_simulation(Mock(), _simulation())

    create.assert_not_called()


def test_successful_report_cannot_be_overwritten(monkeypatch) -> None:
    stored = _report(
        status="succeeded",
        aggregation_status="succeeded",
        aggregate_output_uri="gs://private-stage12/reports/aggregate.json",
        aggregate_output_sha256=DIGEST_A,
        aggregate_schema_version=1,
        completed_at=NOW + timedelta(minutes=1),
    )
    row = Stage12ComparisonReport(**report_insert_values(stored))
    update = Mock()
    monkeypatch.setattr(
        services,
        "read_comparison_report",
        lambda *_args, **_kwargs: row,
    )
    monkeypatch.setattr(services, "update_comparison_report", update)
    changed = stored.model_copy(update={"aggregate_output_sha256": DIGEST_B})

    with pytest.raises(ComparisonRunIdentityError, match="aggregate_output_sha256"):
        services.replace_report_lifecycle(Mock(), changed)

    update.assert_not_called()


def test_successful_report_can_record_a_result_comparison(monkeypatch) -> None:
    stored = _report(
        status="succeeded",
        aggregation_status="succeeded",
        aggregate_output_uri="gs://private-stage12/reports/aggregate.json",
        aggregate_output_sha256=DIGEST_A,
        aggregate_schema_version=1,
        completed_at=NOW + timedelta(minutes=1),
        comparison_status="pending",
    )
    completed = stored.model_copy(
        update={
            "comparison_status": ResultComparisonStatus.DIFFERENT,
            "comparison_output_uri": ("gs://private-stage12/reports/comparison.json"),
            "comparison_output_sha256": DIGEST_B,
            "comparison_schema_version": 1,
            "comparison_completed_at": NOW + timedelta(minutes=2),
            "updated_at": NOW + timedelta(minutes=2),
        }
    )
    row = Stage12ComparisonReport(**report_insert_values(stored))
    completed_row = Stage12ComparisonReport(**report_insert_values(completed))
    monkeypatch.setattr(
        services,
        "read_comparison_report",
        lambda *_args, **_kwargs: row,
    )
    update = Mock(return_value=completed_row)
    monkeypatch.setattr(services, "update_report_result_comparison", update)

    result = services.replace_report_result_comparison(Mock(), completed)

    assert result == completed
    update.assert_called_once()


def test_lifecycle_update_cannot_change_result_comparison(monkeypatch) -> None:
    stored = _report(comparison_status="pending")
    row = Stage12ComparisonReport(**report_insert_values(stored))
    monkeypatch.setattr(
        services,
        "read_comparison_report",
        lambda *_args, **_kwargs: row,
    )
    update = Mock()
    monkeypatch.setattr(services, "update_comparison_report", update)

    with pytest.raises(ComparisonRunIdentityError, match="comparison_status"):
        services.replace_report_lifecycle(
            Mock(),
            stored.model_copy(update={"comparison_status": "running"}),
        )

    update.assert_not_called()


def test_successful_simulation_replay_is_read_only(monkeypatch) -> None:
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
    row = Stage12ComparisonSimulation(**simulation_insert_values(stored))
    update = Mock()
    monkeypatch.setattr(
        services,
        "read_comparison_simulation",
        lambda *_args, **_kwargs: row,
    )
    monkeypatch.setattr(services, "update_comparison_simulation", update)

    result = services.replace_simulation_lifecycle(
        Mock(),
        stored.model_copy(update={"updated_at": NOW + timedelta(minutes=2)}),
    )

    assert result == stored
    update.assert_not_called()


def test_successful_simulation_cannot_be_overwritten(monkeypatch) -> None:
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
    row = Stage12ComparisonSimulation(**simulation_insert_values(stored))
    update = Mock()
    monkeypatch.setattr(
        services,
        "read_comparison_simulation",
        lambda *_args, **_kwargs: row,
    )
    monkeypatch.setattr(services, "update_comparison_simulation", update)

    with pytest.raises(ComparisonRunIdentityError, match="output_sha256"):
        services.replace_simulation_lifecycle(
            Mock(),
            stored.model_copy(update={"output_sha256": DIGEST_B}),
        )

    update.assert_not_called()


def test_lifecycle_updates_reject_identity_changes_and_state_reversal() -> None:
    pending = _report()
    changed_identity = pending.model_copy(update={"worker_version": "5.3.0"})
    with pytest.raises(ComparisonRunIdentityError, match="worker_version"):
        require_report_identity(pending, changed_identity)

    require_lifecycle_transition(pending.status, pending.status.RUNNING)
    require_lifecycle_transition(
        pending.status.FAILED,
        pending.status.RUNNING,
    )
    with pytest.raises(ComparisonRunStateTransitionError, match="succeeded to running"):
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
    with pytest.raises(ComparisonRunStateTransitionError, match="succeeded to running"):
        require_aggregation_transition(
            pending.aggregation_status.SUCCEEDED,
            pending.aggregation_status.RUNNING,
        )
    require_result_comparison_transition(
        pending.comparison_status.PENDING,
        pending.comparison_status.RUNNING,
    )
    with pytest.raises(
        ComparisonRunStateTransitionError,
        match="failed to running",
    ):
        require_result_comparison_transition(
            pending.comparison_status.FAILED,
            pending.comparison_status.RUNNING,
        )
    with pytest.raises(
        ComparisonRunStateTransitionError,
        match="not_requested to pending",
    ):
        require_result_comparison_transition(
            pending.comparison_status.NOT_REQUESTED,
            pending.comparison_status.PENDING,
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
