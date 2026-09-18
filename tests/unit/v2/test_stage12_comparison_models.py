"""Schema and persistence tests for temporary Stage 12 comparison records."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, create_engine

from policyengine_api.data.v2.models import (
    Stage12AggregationStatus,
    Stage12ComparisonReport,
    Stage12ComparisonSimulation,
    Stage12RunStatus,
    Stage12SimulationRole,
    V2_METADATA,
)
from policyengine_api.services.v2.comparison_runs.types import (
    ComparisonRunAggregationStatus,
    ComparisonRunLifecycleStatus,
)
from policyengine_api.services.v2.simulations.types import SimulationRole

NOW = datetime(2026, 9, 14, tzinfo=timezone.utc)
EVALUATION_ID = UUID("00000000-0000-4000-8000-000000000001")
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def _engine():
    engine = create_engine("sqlite://")

    @sa.event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    V2_METADATA.create_all(engine)
    return engine


def _report(**changes: object) -> Stage12ComparisonReport:
    fields: dict[str, object] = {
        "evaluation_id": EVALUATION_ID,
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
        "retention_expires_at": NOW + timedelta(days=30),
    }
    fields.update(changes)
    return Stage12ComparisonReport(**fields)


def _simulation(**changes: object) -> Stage12ComparisonSimulation:
    fields: dict[str, object] = {
        "evaluation_id": EVALUATION_ID,
        "role": Stage12SimulationRole.BASELINE,
        "input_sha256": DIGEST_B,
        "worker_version": "5.2.0",
        "modal_application": "policyengine-v2-worker-5-2-0",
        "simulation_callable": "run_simulation",
        "version_manifest_sha256": DIGEST_A,
        "retention_expires_at": NOW + timedelta(days=30),
    }
    fields.update(changes)
    return Stage12ComparisonSimulation(**fields)


def test_comparison_tables_have_only_the_temporary_parent_child_relationship() -> None:
    report_table = V2_METADATA.tables["stage12_evaluation_reports"]
    simulation_table = V2_METADATA.tables["stage12_evaluation_simulations"]

    assert set(sa.inspect(Stage12ComparisonReport).relationships.keys()) == {
        "simulations"
    }
    assert set(sa.inspect(Stage12ComparisonSimulation).relationships.keys()) == {
        "report"
    }
    assert not report_table.foreign_keys
    assert {
        foreign_key.target_fullname for foreign_key in simulation_table.foreign_keys
    } == {"stage12_evaluation_reports.evaluation_id"}
    assert {
        "household_jobs",
        "simulations",
        "reports",
        "report_runs",
        "user_simulation_associations",
        "user_report_associations",
        "runtime_bundles",
    }.isdisjoint({report_table.name, simulation_table.name})


def test_contract_and_table_enum_values_cannot_drift() -> None:
    assert {status.value for status in Stage12RunStatus} == {
        status.value for status in ComparisonRunLifecycleStatus
    }
    assert {status.value for status in Stage12AggregationStatus} == {
        status.value for status in ComparisonRunAggregationStatus
    }
    assert {role.value for role in Stage12SimulationRole} == {
        role.value for role in SimulationRole
    }


def test_parent_identity_is_unique_for_worker_and_manifest() -> None:
    engine = _engine()
    with Session(engine) as session:
        session.add(_report())
        session.commit()
        session.add(_report(evaluation_id=None))
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
        else:
            raise AssertionError("duplicate parent identity was accepted")
    engine.dispose()


def test_child_identity_is_unique_within_a_parent() -> None:
    engine = _engine()
    with Session(engine) as session:
        session.add(_report())
        session.add(_simulation())
        session.commit()
        session.add(_simulation(simulation_execution_id=None))
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
        else:
            raise AssertionError("duplicate child identity was accepted")
    engine.dispose()


def test_distinct_child_roles_can_complete_independently() -> None:
    engine = _engine()
    with Session(engine) as session:
        report = _report()
        baseline = _simulation(
            status=Stage12RunStatus.SUCCEEDED,
            completed_at=NOW,
            output_uri="gs://private-stage12/simulations/baseline.parquet",
            output_sha256=DIGEST_A,
            output_schema_version=1,
            row_identity_columns=["household_id"],
            row_count=100,
            row_identity_sha256=DIGEST_B,
        )
        reform = _simulation(
            role=Stage12SimulationRole.REFORM,
            input_sha256=DIGEST_A,
        )
        session.add(report)
        session.add(baseline)
        session.add(reform)
        session.commit()

        assert baseline.status is Stage12RunStatus.SUCCEEDED
        assert reform.status is Stage12RunStatus.PENDING
    engine.dispose()


def test_database_rejects_success_without_complete_output_metadata() -> None:
    engine = _engine()
    with Session(engine) as session:
        session.add(
            _report(
                status=Stage12RunStatus.SUCCEEDED,
                aggregation_status=Stage12AggregationStatus.SUCCEEDED,
                completed_at=NOW,
            )
        )
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
        else:
            raise AssertionError("successful report without output was accepted")
    engine.dispose()


def test_database_rejects_failed_state_without_bounded_error_code() -> None:
    engine = _engine()
    with Session(engine) as session:
        session.add(_report(status=Stage12RunStatus.FAILED))
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
        else:
            raise AssertionError("failed report without error code was accepted")
    engine.dispose()
