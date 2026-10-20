"""Valid temporary Stage 12 comparison-run records for service and database tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from policyengine_api.services.v2.comparison_runs.types import (
    ComparisonReportRecord,
    ComparisonSimulationRecord,
)

NOW = datetime(2026, 9, 14, tzinfo=UTC)
EVALUATION_ID = UUID("00000000-0000-4000-8000-000000000001")
SIMULATION_ID = UUID("00000000-0000-4000-8000-000000000002")
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def comparison_report_record(**changes: object) -> ComparisonReportRecord:
    """Return a pending comparison report, with ``changes`` applied."""
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


def comparison_simulation_record(**changes: object) -> ComparisonSimulationRecord:
    """Return a pending baseline simulation of the default report, with ``changes``."""
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
