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
    ReportExecutionInput,
)
from policyengine_api.services.v2.simulations.types import (
    SimulationArtifactDescriptor,
    SimulationExecutionInput,
)

CONTRACT_DOCUMENT_ID = "https://policyengine.org/contracts/stage-12-worker-v1.json"
CONTRACT_MODELS: tuple[type[BaseModel], ...] = (
    SimulationExecutionInput,
    ReportExecutionInput,
    SimulationArtifactDescriptor,
    AggregateReportArtifactDescriptor,
    EvaluationReportRecord,
    EvaluationSimulationRecord,
)
EVALUATION_TABLE_MODELS = (
    Stage12EvaluationReport,
    Stage12EvaluationSimulation,
)


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
