"""Contract tests for the Stage 12 report and simulation worker boundary."""

from __future__ import annotations

from copy import deepcopy
from uuid import UUID

from pydantic import ValidationError
import pytest

from policyengine_api.services.v2.reports.types import (
    AggregateReportArtifactDescriptor,
    ReportExecutionInput,
)
from policyengine_api.services.v2.simulations.types import (
    SimulationArtifactDescriptor,
    SimulationExecutionInput,
)

EVALUATION_ID = UUID("00000000-0000-4000-8000-000000000001")
BASELINE_ID = UUID("00000000-0000-4000-8000-000000000002")
REFORM_ID = UUID("00000000-0000-4000-8000-000000000003")
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64


def _bundle() -> dict[str, object]:
    return {
        "policyengine_version": "5.2.0",
        "country_package_name": "policyengine-us",
        "country_package_version": "1.900.0",
        "dataset": {
            "identity": "populace_us_2024",
            "uri": "hf://policyengine/populace-us/populace_us_2024.h5@revision",
            "artifact_revision": "revision",
            "data_package_name": "policyengine-us-data",
            "data_package_version": "1.0.0",
        },
        "bundle_manifest_sha256": DIGEST_A,
    }


def _population_artifact() -> dict[str, object]:
    return {
        "uri": "gs://private-stage12/inputs/population.parquet",
        "media_type": "application/vnd.apache.parquet",
        "content_sha256": DIGEST_B,
        "size_bytes": 123,
    }


def _simulation(*, role: str, simulation_id: UUID) -> dict[str, object]:
    return {
        "contract_version": 1,
        "evaluation_id": str(EVALUATION_ID),
        "simulation_execution_id": str(simulation_id),
        "role": role,
        "policy": {},
        "population": {
            "kind": "dataset",
            "artifact": _population_artifact(),
        },
        "year": 2026,
        "geography": {"country": "US", "region": "us"},
        "options": {},
        "requested_output": {
            "schema_version": 1,
            "variables": ["household_net_income", "household_weight"],
        },
        "bundle": _bundle(),
    }


def _report() -> dict[str, object]:
    return {
        "contract_version": 1,
        "evaluation_id": str(EVALUATION_ID),
        "baseline": _simulation(role="baseline", simulation_id=BASELINE_ID),
        "reform": _simulation(role="reform", simulation_id=REFORM_ID),
        "requested_aggregates": ["budget", "poverty", "winners_and_losers"],
    }


def test_report_contract_requires_two_aligned_single_simulations() -> None:
    report = ReportExecutionInput.model_validate(_report())

    assert report.baseline.role == "baseline"
    assert report.reform.role == "reform"
    assert (
        report.baseline.simulation_execution_id != report.reform.simulation_execution_id
    )
    assert report.baseline.geography.country == "us"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda report: report["baseline"].update({"reform": {}}),
            "Extra inputs are not permitted",
        ),
        (
            lambda report: report["reform"].update({"role": "baseline"}),
            "reform input must use the reform role",
        ),
        (
            lambda report: report["reform"].update(
                {"simulation_execution_id": str(BASELINE_ID)}
            ),
            "simulation identifiers must differ",
        ),
        (
            lambda report: report["reform"].update({"year": 2027}),
            "baseline and reform year must match",
        ),
        (
            lambda report: report["reform"]["bundle"]["dataset"].update(
                {"artifact_revision": "other"}
            ),
            "baseline and reform bundle must match",
        ),
    ],
)
def test_report_contract_rejects_combined_or_misaligned_inputs(
    mutate, message: str
) -> None:
    report = _report()
    mutate(report)

    with pytest.raises(ValidationError, match=message):
        ReportExecutionInput.model_validate(report)


def test_simulation_contract_rejects_unknown_fields_and_non_gcs_artifacts() -> None:
    simulation = _simulation(role="baseline", simulation_id=BASELINE_ID)
    simulation["unknown"] = True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SimulationExecutionInput.model_validate(simulation)

    simulation = _simulation(role="baseline", simulation_id=BASELINE_ID)
    simulation["population"]["artifact"]["uri"] = "https://public.test/data"
    with pytest.raises(ValidationError, match="String should match pattern"):
        SimulationExecutionInput.model_validate(simulation)


def test_geography_filter_fields_are_all_present_or_all_absent() -> None:
    simulation = _simulation(role="baseline", simulation_id=BASELINE_ID)
    simulation["geography"]["filter_field"] = "state_code"

    with pytest.raises(ValidationError, match="must be supplied together"):
        SimulationExecutionInput.model_validate(simulation)


def test_artifact_descriptors_retain_identity_and_bundle_provenance() -> None:
    simulation_artifact = SimulationArtifactDescriptor.model_validate(
        {
            "contract_version": 1,
            "evaluation_id": str(EVALUATION_ID),
            "simulation_execution_id": str(BASELINE_ID),
            "role": "baseline",
            "artifact": {
                **_population_artifact(),
                "content_sha256": DIGEST_C,
            },
            "output_schema_version": 1,
            "row_identity": {
                "schema_version": 1,
                "identifier_columns": ["household_id"],
                "row_count": 100,
                "identity_sha256": DIGEST_B,
            },
            "bundle": _bundle(),
            "calculation_provenance": {
                "spm_config": {"scenario": "official"},
                "spm_provenance": {"forecast_sha256": DIGEST_A},
            },
        }
    )
    report_artifact = AggregateReportArtifactDescriptor.model_validate(
        {
            "contract_version": 1,
            "evaluation_id": str(EVALUATION_ID),
            "artifact": {
                "uri": "gs://private-stage12/reports/aggregate.json",
                "media_type": "application/json",
                "content_sha256": DIGEST_A,
                "size_bytes": 456,
            },
            "aggregate_schema_version": 1,
            "baseline_artifact_sha256": DIGEST_C,
            "reform_artifact_sha256": DIGEST_B,
            "bundle": _bundle(),
        }
    )

    assert simulation_artifact.row_identity.identifier_columns == ("household_id",)
    assert simulation_artifact.calculation_provenance == {
        "spm_config": {"scenario": "official"},
        "spm_provenance": {"forecast_sha256": DIGEST_A},
    }
    assert (
        report_artifact.baseline_artifact_sha256
        == simulation_artifact.artifact.content_sha256
    )


def test_contract_models_are_immutable_and_reject_duplicate_lists() -> None:
    report = ReportExecutionInput.model_validate(_report())
    with pytest.raises(ValidationError):
        ReportExecutionInput.model_validate(
            {**_report(), "requested_aggregates": ["budget", "budget"]}
        )
    with pytest.raises(ValidationError):
        SimulationExecutionInput.model_validate(
            {
                **deepcopy(_simulation(role="baseline", simulation_id=BASELINE_ID)),
                "requested_output": {
                    "schema_version": 1,
                    "variables": ["income", "income"],
                },
            }
        )
    with pytest.raises(ValidationError):
        report.baseline.year = 2027
