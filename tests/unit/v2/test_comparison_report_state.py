"""Pin every state rule of a comparison report record and their precedence."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from policyengine_api.services.v2.comparison_runs.types import ComparisonReportRecord

NOW = datetime(2026, 9, 14, tzinfo=UTC)
DIGEST = "a" * 64
AGGREGATE_OUTPUT = {
    "aggregate_output_uri": "gs://private-stage12/reports/aggregate.json",
    "aggregate_output_sha256": DIGEST,
    "aggregate_schema_version": 1,
}
COMPARISON_OUTPUT = {
    "comparison_output_uri": "gs://private-stage12/reports/comparison.json",
    "comparison_output_sha256": DIGEST,
    "comparison_schema_version": 1,
}
SUCCEEDED = {
    "status": "succeeded",
    "aggregation_status": "succeeded",
    "completed_at": NOW,
    **AGGREGATE_OUTPUT,
}


def _report(**changes: object) -> ComparisonReportRecord:
    fields: dict[str, object] = {
        "evaluation_id": UUID("00000000-0000-4000-8000-000000000001"),
        "status": "pending",
        "aggregation_status": "not_started",
        "environment": "test",
        "calculation_flow": "economy",
        "originating_request_id": "request-1",
        "production_identity": "production-job-1",
        "worker_version": "5.2.0",
        "modal_application": "policyengine-v2-worker-5-2-0",
        "report_coordinator_callable": "coordinate_report",
        "version_manifest_sha256": DIGEST,
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


@pytest.mark.parametrize(
    "changes",
    [
        {},
        SUCCEEDED,
        {"status": "failed", "error_code": "worker_failed"},
        {"status": "skipped", "error_code": "not_applicable"},
        {"comparison_status": "pending"},
        {"comparison_status": "running"},
        {**SUCCEEDED, "comparison_status": "matched", "comparison_completed_at": NOW}
        | COMPARISON_OUTPUT,
        {**SUCCEEDED, "comparison_status": "different", "comparison_completed_at": NOW}
        | COMPARISON_OUTPUT,
        {
            "comparison_status": "failed",
            "comparison_completed_at": NOW,
            "comparison_error_code": "compare_failed",
            "comparison_error_summary": "The comparison failed.",
        },
    ],
)
def test_consistent_reports_are_accepted(changes: dict[str, object]) -> None:
    assert _report(**changes).evaluation_id is not None


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {"created_at": NOW.replace(tzinfo=None)},
            "comparison retention timestamps must include a timezone",
        ),
        (
            {"aggregate_output_uri": AGGREGATE_OUTPUT["aggregate_output_uri"]},
            "aggregate output fields must be supplied together",
        ),
        (
            {**SUCCEEDED, "aggregation_status": "running"},
            "a successful report requires successful aggregation",
        ),
        (
            {"status": "succeeded", "aggregation_status": "succeeded"},
            "a successful report requires an aggregate output",
        ),
        (
            {**SUCCEEDED, "completed_at": None},
            "a successful report requires completed_at",
        ),
        ({"status": "failed"}, "a failed or skipped report requires an error_code"),
        ({"status": "skipped"}, "a failed or skipped report requires an error_code"),
        (
            {"comparison_output_uri": COMPARISON_OUTPUT["comparison_output_uri"]},
            "an incomplete comparison cannot reference an output artifact",
        ),
        (
            {"comparison_status": "pending", "comparison_completed_at": NOW},
            "an incomplete comparison cannot have completed_at",
        ),
        (
            {"comparison_status": "running", "comparison_error_code": "early"},
            "an incomplete comparison cannot have an error_code",
        ),
        (
            {"comparison_error_summary": "early"},
            "an incomplete comparison cannot have an error_summary",
        ),
        (
            {"comparison_status": "matched", "comparison_completed_at": NOW},
            "a completed comparison requires an output artifact",
        ),
        (
            {"comparison_status": "different", **COMPARISON_OUTPUT},
            "a completed comparison requires completed_at",
        ),
        (
            {
                "comparison_status": "matched",
                "comparison_completed_at": NOW,
                "comparison_error_code": "late",
                **COMPARISON_OUTPUT,
            },
            "a completed comparison cannot have an error_code",
        ),
        (
            {
                "comparison_status": "matched",
                "comparison_completed_at": NOW,
                "comparison_error_summary": "late",
                **COMPARISON_OUTPUT,
            },
            "a completed comparison cannot have an error_summary",
        ),
        (
            {
                "comparison_status": "failed",
                "comparison_completed_at": NOW,
                "comparison_error_code": "compare_failed",
                "comparison_schema_version": 1,
            },
            "a failed comparison cannot reference an output artifact",
        ),
        (
            {"comparison_status": "failed", "comparison_error_code": "compare_failed"},
            "a failed comparison requires completed_at",
        ),
        (
            {"comparison_status": "failed", "comparison_completed_at": NOW},
            "a failed comparison requires an error_code",
        ),
    ],
)
def test_each_inconsistent_state_is_rejected_with_its_message(
    changes: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=re.escape(message)):
        _report(**changes)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {
                "retention_expires_at": NOW + timedelta(days=31),
                "aggregate_output_uri": AGGREGATE_OUTPUT["aggregate_output_uri"],
            },
            "comparison retention must not exceed 30 days",
        ),
        (
            {
                "status": "succeeded",
                "aggregation_status": "running",
                "aggregate_output_uri": AGGREGATE_OUTPUT["aggregate_output_uri"],
            },
            "aggregate output fields must be supplied together",
        ),
        (
            {"status": "succeeded", "aggregation_status": "running"},
            "a successful report requires successful aggregation",
        ),
        (
            {
                "status": "failed",
                "comparison_status": "failed",
            },
            "a failed or skipped report requires an error_code",
        ),
        (
            {
                "comparison_completed_at": NOW,
                "comparison_error_code": "early",
                **COMPARISON_OUTPUT,
            },
            "an incomplete comparison cannot reference an output artifact",
        ),
        (
            {"comparison_status": "matched", "comparison_error_code": "late"},
            "a completed comparison requires an output artifact",
        ),
        (
            {"comparison_status": "failed", **COMPARISON_OUTPUT},
            "a failed comparison cannot reference an output artifact",
        ),
    ],
)
def test_the_first_violated_rule_is_the_one_reported(
    changes: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError) as raised:
        _report(**changes)

    errors = raised.value.errors()
    assert len(errors) == 1
    assert errors[0]["msg"] == f"Value error, {message}"
