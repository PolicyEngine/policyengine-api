"""Deterministic export of the Stage 12 cross-service contracts."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from policyengine_api.data.v2.models import (
    Stage12EvaluationReport,
    Stage12EvaluationSimulation,
)

from policyengine_api.services.v2.evaluation_executions.types import (
    EvaluationReportRecord,
    EvaluationSimulationRecord,
)
from policyengine_api.services.v2.reports.types import (
    AggregateReportArtifactDescriptor,
    AggregateReportArtifactPayload,
    ReportExecutionInput,
)
from policyengine_api.services.v2.simulations.types import (
    SIMULATION_PARQUET_PAYLOAD_CONTRACT,
    SimulationArtifactDescriptor,
    SimulationExecutionInput,
    SimulationParquetPayloadContract,
)

CONTRACT_DOCUMENT_ID = "https://policyengine.org/contracts/stage-12-worker-v1.json"
CONTRACT_MODELS: tuple[type[BaseModel], ...] = (
    SimulationExecutionInput,
    ReportExecutionInput,
    SimulationArtifactDescriptor,
    SimulationParquetPayloadContract,
    AggregateReportArtifactDescriptor,
    AggregateReportArtifactPayload,
    EvaluationReportRecord,
    EvaluationSimulationRecord,
)
EVALUATION_TABLE_MODELS = (
    Stage12EvaluationReport,
    Stage12EvaluationSimulation,
)

SEMANTIC_RULES = {
    "AggregateReportArtifactPayload": (
        "requested_aggregates contains at least one unique value",
        "result is a finite JSON object produced from the two aligned simulation artifacts",
    ),
    "EvaluationReportRecord": (
        "retention timestamps are timezone-aware and span more than zero and no more than 30 days",
        "aggregate output fields are either all absent or all present",
        "a succeeded report has succeeded aggregation, a complete aggregate output, and completed_at",
        "a failed or skipped report has an error_code",
    ),
    "EvaluationSimulationRecord": (
        "retention timestamps are timezone-aware and span more than zero and no more than 30 days",
        "simulation output fields are either all absent or all present",
        "row_identity_columns is non-empty and unique when present",
        "a succeeded simulation has a complete output and completed_at",
        "a failed or skipped simulation has an error_code",
    ),
    "GeographySelection": (
        "filter_field and filter_value are supplied together",
        "filter_strategy is present only with filter_field and filter_value",
    ),
    "ReportExecutionInput": (
        "baseline has the baseline role and reform has the reform role",
        "both simulations name the report evaluation_id and use distinct execution identifiers",
        "population, year, geography, options, requested output, and bundle provenance match between simulations",
        "requested_aggregates contains unique values",
    ),
    "RequestedSimulationOutput": ("variables contains unique values",),
    "RowIdentity": ("identifier_columns contains unique values",),
    "SimulationParquetPayloadContract": (
        "every entity table contains a unique {entity}_id column",
        "rows are sorted by entity name and then by entity identifier before encoding",
        "the Parquet metadata records the original per-entity data types",
    ),
}


def _table_contract(model: type[object]) -> dict[str, object]:
    """Describe one canonical SQLModel table without duplicating its definition."""

    inspected = sa.inspect(model)
    if inspected is None:
        raise TypeError(f"{model!r} is not a mapped SQLModel")
    table = inspected.local_table
    assert table is not None
    dialect = postgresql.dialect()
    unique_constraints = sorted(
        (
            {
                "name": constraint.name,
                "columns": [column.name for column in constraint.columns],
            }
            for constraint in table.constraints
            if isinstance(constraint, sa.UniqueConstraint)
        ),
        key=lambda item: str(item["name"]),
    )
    check_constraints = sorted(
        (
            {
                "name": constraint.name,
                "expression": str(constraint.sqltext),
            }
            for constraint in table.constraints
            if isinstance(constraint, sa.CheckConstraint)
        ),
        key=lambda item: str(item["name"]),
    )
    foreign_keys = sorted(
        (
            {
                "name": constraint.name,
                "columns": [column.name for column in constraint.columns],
                "targets": [element.target_fullname for element in constraint.elements],
                "ondelete": constraint.ondelete,
            }
            for constraint in table.foreign_key_constraints
        ),
        key=lambda item: str(item["name"]),
    )
    indexes = sorted(
        (
            {
                "name": index.name,
                "columns": [column.name for column in index.columns],
                "unique": index.unique,
            }
            for index in table.indexes
        ),
        key=lambda item: str(item["name"]),
    )
    return {
        "name": table.name,
        "columns": [
            {
                "name": column.name,
                "type": column.type.compile(dialect=dialect),
                "nullable": column.nullable,
                "primary_key": column.primary_key,
            }
            for column in table.columns
        ],
        "unique_constraints": unique_constraints,
        "check_constraints": check_constraints,
        "foreign_keys": foreign_keys,
        "indexes": indexes,
    }


def contract_document() -> dict[str, object]:
    """Return the complete deterministic contract document."""

    return {
        "$id": CONTRACT_DOCUMENT_ID,
        "contract_version": 1,
        "schema_owner": "PolicyEngine/policyengine-api",
        "schemas": {
            model.__name__: model.model_json_schema(mode="validation")
            for model in CONTRACT_MODELS
        },
        "artifact_payload_contracts": {
            "aggregate_report_json": {
                "$ref": "#/schemas/AggregateReportArtifactPayload"
            },
            "simulation_parquet": SIMULATION_PARQUET_PAYLOAD_CONTRACT.model_dump(
                mode="json"
            ),
        },
        "semantic_rules": {
            model_name: list(rules)
            for model_name, rules in sorted(SEMANTIC_RULES.items())
        },
        "tables": {
            model.__tablename__: _table_contract(model)
            for model in EVALUATION_TABLE_MODELS
        },
    }


def render_contract_document() -> str:
    """Render the contract using stable key and whitespace ordering."""

    return (
        json.dumps(
            contract_document(),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )


def write_contract_document(path: Path) -> None:
    """Write the generated contract to an explicit repository path."""

    path.write_text(render_contract_document(), encoding="utf-8")
