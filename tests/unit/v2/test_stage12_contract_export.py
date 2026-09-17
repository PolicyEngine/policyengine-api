"""Tests for the generated Stage 12 cross-service contract document."""

from __future__ import annotations

import json
from pathlib import Path

from policyengine_api.services.v2.stage12_contract_export import (
    CONTRACT_DOCUMENT_ID,
    render_contract_document,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
GENERATED_CONTRACT = REPOSITORY_ROOT / "docs/generated/stage12_worker_contracts.json"


def test_generated_stage12_contract_is_current() -> None:
    assert GENERATED_CONTRACT.read_text(encoding="utf-8") == render_contract_document()


def test_generated_stage12_contract_identifies_owner_and_required_schemas() -> None:
    contract = json.loads(GENERATED_CONTRACT.read_text(encoding="utf-8"))

    assert contract["$id"] == CONTRACT_DOCUMENT_ID
    assert contract["contract_version"] == 1
    assert contract["schema_owner"] == "PolicyEngine/policyengine-api"
    assert set(contract["schemas"]) == {
        "AggregateReportArtifactDescriptor",
        "AggregateReportArtifactPayload",
        "EvaluationReportRecord",
        "EvaluationSimulationRecord",
        "ReportExecutionInput",
        "SimulationArtifactDescriptor",
        "SimulationExecutionInput",
        "SimulationParquetPayloadContract",
    }
    assert contract["artifact_payload_contracts"]["aggregate_report_json"] == {
        "$ref": "#/schemas/AggregateReportArtifactPayload"
    }
    parquet = contract["artifact_payload_contracts"]["simulation_parquet"]
    assert parquet["compression"] == "zstd"
    assert parquet["entity_column"] == "__entity__"
    assert parquet["identifier_column_template"] == "{entity}_id"
    assert contract["semantic_rules"]["ReportExecutionInput"]
    assert set(contract["tables"]) == {
        "stage12_evaluation_reports",
        "stage12_evaluation_simulations",
    }
    report_table = contract["tables"]["stage12_evaluation_reports"]
    child_table = contract["tables"]["stage12_evaluation_simulations"]
    assert {column["name"] for column in report_table["columns"]} >= {
        "evaluation_id",
        "production_identity",
        "version_manifest_sha256",
        "aggregate_output_uri",
        "retention_expires_at",
    }
    assert child_table["foreign_keys"] == [
        {
            "columns": ["evaluation_id"],
            "name": (
                "fk_stage12_evaluation_simulations_evaluation_id_"
                "stage12_evaluation_reports"
            ),
            "ondelete": "CASCADE",
            "targets": ["stage12_evaluation_reports.evaluation_id"],
        }
    ]
