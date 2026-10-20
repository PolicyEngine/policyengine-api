"""Service and SQL statement tests for temporary comparison-run persistence."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

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
from tests.unit.v2.comparison_run_support import (
    DIGEST_A,
    DIGEST_B,
    EVALUATION_ID,
    NOW,
    comparison_report_record,
    comparison_simulation_record,
)


def test_insert_statements_use_the_parent_and_child_identities() -> None:
    report_statement = (
        creates.insert(creates.Stage12ComparisonReport)
        .values(**report_insert_values(comparison_report_record()))
        .on_conflict_do_nothing(constraint="uq_stage12_eval_reports_identity")
        .returning(creates.Stage12ComparisonReport.evaluation_id)
    )
    simulation_statement = (
        creates.insert(creates.Stage12ComparisonSimulation)
        .values(**simulation_insert_values(comparison_simulation_record()))
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
    report = comparison_report_record()
    simulation = comparison_simulation_record()
    report_row = Stage12ComparisonReport(**report_insert_values(report))
    simulation_row = Stage12ComparisonSimulation(**simulation_insert_values(simulation))

    assert report_record(report_row) == report
    assert simulation_record(simulation_row) == simulation


def test_conflicting_report_creation_reuses_the_stored_identity(monkeypatch) -> None:
    stored = comparison_report_record()
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
    stored = comparison_report_record()
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
    parent_row = Stage12ComparisonReport(
        **report_insert_values(comparison_report_record())
    )
    stored = comparison_simulation_record(
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
    retried = comparison_simulation_record(simulation_execution_id=uuid4())
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
    parent_row = Stage12ComparisonReport(
        **report_insert_values(comparison_report_record())
    )
    child = comparison_simulation_record(**{field_name: other_value})
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
        services.create_or_resolve_simulation(Mock(), comparison_simulation_record())

    create.assert_not_called()


def test_successful_report_cannot_be_overwritten(monkeypatch) -> None:
    stored = comparison_report_record(
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
    stored = comparison_report_record(
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
    stored = comparison_report_record(comparison_status="pending")
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


def test_comparison_contract_rejects_completed_state_without_artifact() -> None:
    with pytest.raises(ValueError, match="requires an output artifact"):
        comparison_report_record(
            comparison_status="different",
            comparison_completed_at=NOW,
        )


def test_successful_simulation_replay_is_read_only(monkeypatch) -> None:
    stored = comparison_simulation_record(
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
    stored = comparison_simulation_record(
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
    pending = comparison_report_record()
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
    [comparison_report_record, comparison_simulation_record],
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
