"""Database updates for temporary Stage 12 evaluation lifecycle fields."""

from __future__ import annotations

from sqlmodel import Session

from policyengine_api.data.v2.models import (
    Stage12AggregationStatus,
    Stage12EvaluationReport,
    Stage12EvaluationSimulation,
    Stage12EvaluationStatus,
)
from policyengine_api.services.v2.evaluation_executions.types import (
    EvaluationReportRecord,
    EvaluationSimulationRecord,
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


def update_evaluation_report(
    session: Session,
    row: Stage12EvaluationReport,
    record: EvaluationReportRecord,
) -> Stage12EvaluationReport:
    row.status = Stage12EvaluationStatus(record.status.value)
    row.aggregation_status = Stage12AggregationStatus(record.aggregation_status.value)
    for field_name in REPORT_MUTABLE_FIELDS:
        setattr(row, field_name, getattr(record, field_name))
    session.add(row)
    session.flush()
    session.refresh(row)
    return row


def update_evaluation_simulation(
    session: Session,
    row: Stage12EvaluationSimulation,
    record: EvaluationSimulationRecord,
) -> Stage12EvaluationSimulation:
    row.status = Stage12EvaluationStatus(record.status.value)
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
