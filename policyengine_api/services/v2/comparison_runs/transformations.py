"""Pure conversions between Stage 12 comparison contracts and SQLModel rows."""

from __future__ import annotations

from typing import Any

from policyengine_api.data.v2.models import (
    Stage12AggregationStatus,
    Stage12ComparisonReport,
    Stage12ComparisonSimulation,
    Stage12ResultComparisonStatus,
    Stage12RunStatus,
    Stage12SimulationRole,
)
from policyengine_api.services.v2.comparison_runs.types import (
    ComparisonReportRecord,
    ComparisonSimulationRecord,
)


def report_insert_values(record: ComparisonReportRecord) -> dict[str, Any]:
    """Return a report record's column values, with statuses as the table's enums."""
    values = record.model_dump(mode="python")
    values["status"] = Stage12RunStatus(record.status.value)
    values["aggregation_status"] = Stage12AggregationStatus(
        record.aggregation_status.value
    )
    values["comparison_status"] = Stage12ResultComparisonStatus(
        record.comparison_status.value
    )
    return values


def simulation_insert_values(record: ComparisonSimulationRecord) -> dict[str, Any]:
    """Return a simulation record's column values in the table's types.

    Status and role become the table's enums, and row_identity_columns a list.
    """
    values = record.model_dump(mode="python")
    values["status"] = Stage12RunStatus(record.status.value)
    values["role"] = Stage12SimulationRole(record.role.value)
    values["row_identity_columns"] = (
        list(record.row_identity_columns)
        if record.row_identity_columns is not None
        else None
    )
    return values


def report_record(row: Stage12ComparisonReport) -> ComparisonReportRecord:
    """Rebuild the validated contract record from a stored report row.

    Raise pydantic.ValidationError if the row breaks the contract's state rules.
    """
    return ComparisonReportRecord.model_validate(
        {
            field_name: getattr(row, field_name)
            for field_name in ComparisonReportRecord.model_fields
        }
    )


def simulation_record(
    row: Stage12ComparisonSimulation,
) -> ComparisonSimulationRecord:
    """Rebuild the validated contract record from a stored simulation row.

    Raise pydantic.ValidationError if the row breaks the contract's state rules.
    """
    return ComparisonSimulationRecord.model_validate(
        {
            field_name: getattr(row, field_name)
            for field_name in ComparisonSimulationRecord.model_fields
        }
    )
