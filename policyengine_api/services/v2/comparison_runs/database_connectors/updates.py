"""Database updates for temporary Stage 12 comparison-run lifecycle fields."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import update
from sqlmodel import Session, col

from policyengine_api.data.v2.models import (
    Stage12AggregationStatus,
    Stage12ComparisonReport,
    Stage12ComparisonSimulation,
    Stage12ResultComparisonStatus,
    Stage12RunStatus,
)
from policyengine_api.services.v2.comparison_runs.types import (
    ComparisonReportRecord,
    ComparisonSimulationRecord,
)

REPORT_MUTABLE_FIELDS = (
    "coordinator_invocation_id",
    "error_code",
    "error_summary",
    "aggregate_output_uri",
    "aggregate_output_sha256",
    "aggregate_schema_version",
    "updated_at",
    "started_at",
    "completed_at",
)
SIMULATION_MUTABLE_FIELDS = (
    "modal_invocation_id",
    "error_code",
    "error_summary",
    "output_uri",
    "output_sha256",
    "output_schema_version",
    "row_count",
    "row_identity_sha256",
    "updated_at",
    "started_at",
    "completed_at",
)
REPORT_COMPARISON_FIELDS = (
    "comparison_output_uri",
    "comparison_output_sha256",
    "comparison_schema_version",
    "comparison_completed_at",
    "comparison_error_code",
    "comparison_error_summary",
    "updated_at",
)


def update_comparison_report(
    session: Session,
    row: Stage12ComparisonReport,
    record: ComparisonReportRecord,
) -> Stage12ComparisonReport:
    row.status = Stage12RunStatus(record.status.value)
    row.aggregation_status = Stage12AggregationStatus(record.aggregation_status.value)
    for field_name in REPORT_MUTABLE_FIELDS:
        setattr(row, field_name, getattr(record, field_name))
    session.add(row)
    session.flush()
    session.refresh(row)
    return row


def update_comparison_simulation(
    session: Session,
    row: Stage12ComparisonSimulation,
    record: ComparisonSimulationRecord,
) -> Stage12ComparisonSimulation:
    row.status = Stage12RunStatus(record.status.value)
    row.row_identity_columns = (
        list(record.row_identity_columns)
        if record.row_identity_columns is not None
        else None
    )
    for field_name in SIMULATION_MUTABLE_FIELDS:
        setattr(row, field_name, getattr(record, field_name))
    session.add(row)
    session.flush()
    session.refresh(row)
    return row


def update_report_result_comparison(
    session: Session,
    row: Stage12ComparisonReport,
    record: ComparisonReportRecord,
) -> Stage12ComparisonReport:
    row.comparison_status = Stage12ResultComparisonStatus(
        record.comparison_status.value
    )
    for field_name in REPORT_COMPARISON_FIELDS:
        setattr(row, field_name, getattr(record, field_name))
    session.add(row)
    session.flush()
    session.refresh(row)
    return row


def attach_simulation_invocation_statement(
    *,
    simulation_execution_id: UUID,
    expected_placeholder: str,
    modal_invocation_id: str,
    updated_at: datetime,
) -> Any:
    """Build one compare-and-set update for a Modal child invocation."""

    return (
        update(Stage12ComparisonSimulation)
        .where(
            col(Stage12ComparisonSimulation.simulation_execution_id)
            == simulation_execution_id,
            col(Stage12ComparisonSimulation.modal_invocation_id)
            == expected_placeholder,
        )
        .values(
            modal_invocation_id=modal_invocation_id,
            updated_at=updated_at,
        )
        .returning(col(Stage12ComparisonSimulation.simulation_execution_id))
    )


def attach_simulation_invocation(
    session: Session,
    *,
    simulation_execution_id: UUID,
    expected_placeholder: str,
    modal_invocation_id: str,
    updated_at: datetime,
) -> UUID | None:
    return session.execute(
        attach_simulation_invocation_statement(
            simulation_execution_id=simulation_execution_id,
            expected_placeholder=expected_placeholder,
            modal_invocation_id=modal_invocation_id,
            updated_at=updated_at,
        )
    ).scalar_one_or_none()
