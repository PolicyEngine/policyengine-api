"""Pure conversions between Stage 12 contract records and SQLModel rows."""

from __future__ import annotations

from typing import Any

from policyengine_api.data.v2.models import (
    Stage12AggregationStatus,
    Stage12EvaluationReport,
    Stage12EvaluationSimulation,
    Stage12EvaluationStatus,
    Stage12SimulationRole,
)
from policyengine_api.services.v2.evaluation_executions.types import (
    EvaluationReportRecord,
    EvaluationSimulationRecord,
)


def report_insert_values(record: EvaluationReportRecord) -> dict[str, Any]:
    values = record.model_dump(mode="python")
    values["status"] = Stage12EvaluationStatus(record.status.value)
    values["aggregation_status"] = Stage12AggregationStatus(
        record.aggregation_status.value
    )
    return values


def simulation_insert_values(record: EvaluationSimulationRecord) -> dict[str, Any]:
    values = record.model_dump(mode="python")
    values["status"] = Stage12EvaluationStatus(record.status.value)
    values["role"] = Stage12SimulationRole(record.role.value)
    values["row_identity_columns"] = (
        list(record.row_identity_columns)
        if record.row_identity_columns is not None
        else None
    )
    return values


def report_record(row: Stage12EvaluationReport) -> EvaluationReportRecord:
    return EvaluationReportRecord.model_validate(
        {
            field_name: getattr(row, field_name)
            for field_name in EvaluationReportRecord.model_fields
        }
    )


def simulation_record(
    row: Stage12EvaluationSimulation,
) -> EvaluationSimulationRecord:
    return EvaluationSimulationRecord.model_validate(
        {
            field_name: getattr(row, field_name)
            for field_name in EvaluationSimulationRecord.model_fields
        }
    )
