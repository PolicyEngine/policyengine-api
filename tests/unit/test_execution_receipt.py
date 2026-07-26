import json
from pathlib import Path

import pytest
import yaml

from policyengine_api.execution_receipt import (
    build_economy_execution_receipt,
    build_household_execution_receipt,
    execution_receipt_matches_result,
    execution_result_sha256,
    is_valid_execution_receipt,
)
from tests.fixtures.execution_receipt import (
    DATASET_SHA256,
    ECONOMY_POLICYENGINE_BUNDLE,
    ECONOMY_RESULT,
    HOUSEHOLD_REQUEST,
    HOUSEHOLD_RESULT,
)


pytest_plugins = ("tests.fixtures.execution_receipt",)

CONTRACT_FIXTURE = Path(__file__).parents[1] / "fixtures" / "execution_receipt_v1.json"
OPENAPI_SPEC = Path(__file__).parents[2] / "policyengine_api" / "openapi_spec.yaml"


def test__given_household_calculation__then_receipt_matches_v1_contract(
    mock_execution_receipt_runtime,
):
    # Given
    expected_receipt = json.loads(CONTRACT_FIXTURE.read_text())

    # When
    receipt = build_household_execution_receipt(
        country_id="us",
        request_payload=HOUSEHOLD_REQUEST,
        result=HOUSEHOLD_RESULT,
    )

    # Then
    assert receipt == expected_receipt


def test__receipt_hashes_use_shared_rfc8785_vectors(mock_execution_receipt_runtime):
    receipt = build_household_execution_receipt(
        country_id="us",
        request_payload=HOUSEHOLD_REQUEST,
        result=HOUSEHOLD_RESULT,
    )

    assert receipt["request_sha256"] == (
        "c70045c3e2fb9e44a191e61c43a40efd35d2fa0ce13f882ed0cb1ac069cc7a43"
    )
    assert receipt["result_sha256"] == (
        "590a28fe655915f57d7a092d9bdc3359f2156e350bfe372da4d7790cb88391eb"
    )


def test__given_provenance_enrichment__then_result_hash_target_is_unchanged():
    # Given
    enriched_result = {
        **ECONOMY_RESULT,
        "policyengine_bundle": ECONOMY_POLICYENGINE_BUNDLE,
        "resolved_app_name": "policyengine-simulation-py4-18-9",
        "execution_receipt": {"schema_version": 1},
    }

    # When / Then
    assert execution_result_sha256(enriched_result) == execution_result_sha256(
        ECONOMY_RESULT
    )


def test__given_receipt_for_different_result__then_integrity_check_rejects_it(
    mock_execution_receipt_runtime,
):
    # Given
    receipt = build_household_execution_receipt(
        country_id="us",
        request_payload=HOUSEHOLD_REQUEST,
        result=HOUSEHOLD_RESULT,
    )

    # When / Then
    assert receipt is not None
    assert not execution_receipt_matches_result(receipt, {"different": "result"})


def test__non_finite_result__is_rejected_before_receipt_is_emitted(
    mock_execution_receipt_runtime,
):
    with pytest.raises(ValueError, match="finite JSON numbers"):
        build_household_execution_receipt(
            country_id="us",
            request_payload=HOUSEHOLD_REQUEST,
            result={"not_json": float("nan")},
        )


def test__given_resolved_economy_bundle__then_receipt_uses_runtime_identity(
    mock_execution_receipt_runtime,
):
    # When
    receipt = build_economy_execution_receipt(
        country_id="us",
        policyengine_bundle=ECONOMY_POLICYENGINE_BUNDLE,
        result=ECONOMY_RESULT,
        resolved_app_name="policyengine-simulation-py4-18-9",
        run_id="run-123",
    )

    # Then
    assert receipt is not None
    assert receipt["resolved"]["runtime"] == {
        "name": "policyengine",
        "version": "4.18.9",
        "git_sha": None,
        "artifact": {
            "name": "policyengine-simulation-py4-18-9",
            "version": "4.18.9",
            "uri": None,
            "revision": None,
            "sha256": None,
            "build_id": None,
        },
    }
    assert receipt["resolved"]["model"]["actual"]["version"] == "1.752.2"
    assert receipt["resolved"]["model"]["certified"]["version"] == "1.752.2"
    assert receipt["resolved"]["data"]["actual"] == {
        "name": "populace-data",
        "version": "0.1.0",
        "sha256": None,
        "wheel_url": None,
    }
    assert receipt["resolved"]["population_artifact"]["sha256"] == (DATASET_SHA256)
    assert receipt["run_id"] == "run-123"
    assert len(receipt["result_sha256"]) == 64


def test__given_uncertified_dataset__then_receipt_does_not_copy_certified_hash(
    mock_execution_receipt_runtime,
):
    # Given
    runtime_bundle = {
        **ECONOMY_POLICYENGINE_BUNDLE,
        "data_version": "other-release",
        "dataset": "hf://example/other.h5@other-release",
    }

    # When
    receipt = build_economy_execution_receipt(
        country_id="us",
        policyengine_bundle=runtime_bundle,
        result=ECONOMY_RESULT,
    )

    # Then
    assert receipt is not None
    assert receipt["resolved"]["data"] is None
    assert receipt["resolved"]["population_artifact"]["sha256"] is None
    assert receipt["resolved"]["population_artifact"]["build_id"] == ("other-release")


def test__given_missing_runtime_version__then_no_economy_receipt_is_fabricated(
    mock_execution_receipt_runtime,
):
    # When
    receipt = build_economy_execution_receipt(
        country_id="us",
        policyengine_bundle={
            "model_version": "1.752.2",
            "dataset": "default",
        },
        result=ECONOMY_RESULT,
    )

    # Then
    assert receipt is None


@pytest.mark.parametrize(
    "runtime_bundle",
    [
        {
            "model_version": "1.752.2",
            "policyengine_version": "4.18.9",
            "data_version": None,
            "dataset": "default",
        },
        {
            "model_version": "1.752.2",
            "policyengine_version": "4.18.9",
            "data_version": None,
            "dataset": ECONOMY_POLICYENGINE_BUNDLE["dataset"],
        },
        {
            "model_version": "1.752.2",
            "policyengine_version": "4.18.9",
            "data_version": "release-1",
            "dataset": "populace_us_2024",
        },
    ],
)
def test__given_unresolved_economy_dataset__then_no_receipt_is_fabricated(
    mock_execution_receipt_runtime,
    runtime_bundle,
):
    # When
    receipt = build_economy_execution_receipt(
        country_id="us",
        policyengine_bundle=runtime_bundle,
        result=ECONOMY_RESULT,
    )

    # Then
    assert receipt is None


def test__given_valid_axiom_receipt__then_engine_neutral_validation_accepts_it():
    # Given
    receipt = {
        "schema_version": 1,
        "requested": {
            "engine": "axiom",
            "bundle": None,
            "model": None,
            "data": None,
            "ruleset": "us-federal@2026",
            "population": None,
            "numeric_mode": "decimal",
        },
        "resolved": {
            "runtime": {
                "name": "axiom",
                "version": "0.4.0",
                "git_sha": "abc123",
                "artifact": None,
            },
            "numeric_mode": "decimal",
            "model": None,
            "data": None,
            "ruleset_artifact": {
                "name": "us-federal",
                "version": "2026.1",
                "uri": None,
                "revision": None,
                "sha256": "c" * 64,
                "build_id": None,
            },
            "population_artifact": None,
            "certified_release": None,
            "bundle_trace": None,
        },
        "run_id": "axiom-run-1",
        "created_at": "2026-07-09T12:00:00Z",
        "request_sha256": "d" * 64,
        "result_sha256": "e" * 64,
    }

    # Then
    assert is_valid_execution_receipt(receipt)


def test__given_shallow_or_malformed_receipt__then_validation_rejects_it():
    assert not is_valid_execution_receipt(
        {
            "schema_version": True,
            "requested": {},
            "resolved": {
                "runtime": {"name": "axiom", "version": "0.4.0"},
                "numeric_mode": "decimal",
            },
        }
    )
    assert not is_valid_execution_receipt(
        {
            "schema_version": 1,
            "requested": {},
            "resolved": {
                "runtime": {"name": "axiom"},
                "numeric_mode": "decimal",
            },
        }
    )
    assert not is_valid_execution_receipt(
        {
            "schema_version": 1,
            "requested": {},
            "resolved": {
                "runtime": {
                    "name": "axiom",
                    "version": "0.4.0",
                    "artifact": None,
                },
                "numeric_mode": "decimal",
                "ruleset_artifact": {
                    "name": "rules",
                    "sha256": "not-a-sha256",
                },
            },
        }
    )
    assert not is_valid_execution_receipt(
        {
            "schema_version": 1,
            "requested": {},
            "resolved": {
                "runtime": {
                    "name": "axiom",
                    "version": "0.4.0",
                    "artifact": None,
                },
                "numeric_mode": "decimal",
                "model": {
                    "actual": None,
                    "certified": {
                        "name": "policyengine-us",
                        "version": "1.0.0",
                    },
                },
            },
        }
    )


def test__given_forged_certified_package_sha__then_validation_rejects_it():
    # Given
    receipt = json.loads(CONTRACT_FIXTURE.read_text())
    receipt["resolved"]["model"]["certified"]["sha256"] = "f" * 64

    # When / Then
    assert not is_valid_execution_receipt(receipt)


def test__given_execution_receipt_openapi__then_v1_field_shape_cannot_drift():
    # Given
    fixture = json.loads(CONTRACT_FIXTURE.read_text())
    spec = yaml.safe_load(OPENAPI_SPEC.read_text())
    schemas = spec["components"]["schemas"]

    # Then
    assert set(schemas["ExecutionReceipt"]["properties"]) == set(fixture)
    assert set(schemas["RequestedExecutionAliases"]["properties"]) == set(
        fixture["requested"]
    )
    assert set(schemas["ResolvedExecutionBundle"]["properties"]) == set(
        fixture["resolved"]
    )
    assert set(schemas["RuntimeIdentity"]["properties"]) == set(
        fixture["resolved"]["runtime"]
    )
    assert set(schemas["PackageResolution"]["properties"]) == set(
        fixture["resolved"]["model"]
    )
    assert schemas["PackageResolution"]["required"] == ["actual"]
    assert set(schemas["ArtifactIdentity"]["properties"]) == {
        "name",
        "version",
        "uri",
        "revision",
        "sha256",
        "build_id",
    }
    certified_release = fixture["resolved"]["certified_release"]
    assert set(schemas["CountryReleaseManifest"]["properties"]) == set(
        certified_release
    )
    assert set(schemas["DataPackageVersion"]["properties"]) == set(
        certified_release["data_package"]
    )
    assert set(schemas["ArtifactPathReference"]["properties"]) == set(
        certified_release["datasets"]["populace_us_2024"]
    )
    assert set(schemas["ArtifactPathTemplate"]["properties"]) == set(
        certified_release["region_datasets"]["national"]
    )
    assert set(schemas["CertifiedDataArtifact"]["properties"]) == set(
        certified_release["certified_data_artifact"]
    )
    assert set(schemas["DataCertification"]["properties"]) == set(
        certified_release["certification"]
    )
    assert schemas["ResolvedExecutionBundle"]["properties"]["certified_release"][
        "allOf"
    ][0]["$ref"].endswith("/CountryReleaseManifest")
    assert schemas["CountryReleaseManifest"]["properties"]["datasets"][
        "additionalProperties"
    ]["$ref"].endswith("/ArtifactPathReference")
    assert schemas["CountryReleaseManifest"]["properties"]["region_datasets"][
        "additionalProperties"
    ]["$ref"].endswith("/ArtifactPathTemplate")

    calculate_properties = spec["paths"]["/{country_id}/calculate"]["post"][
        "responses"
    ][200]["content"]["application/json"]["schema"]["properties"]
    economy_result_properties = spec["paths"][
        "/{country_id}/economy/{policy_id}/over/{baseline_policy_id}"
    ]["get"]["responses"][200]["content"]["application/json"]["schema"]["properties"][
        "result"
    ]["properties"]
    assert calculate_properties["execution_receipt"]["$ref"].endswith(
        "/ExecutionReceipt"
    )
    persisted_household_properties = spec["paths"][
        "/{country_id}/household/{household_id}/policy/{policy_id}"
    ]["get"]["responses"][200]["content"]["application/json"]["schema"]["properties"]
    assert persisted_household_properties["execution_receipt"]["$ref"].endswith(
        "/ExecutionReceipt"
    )
    assert economy_result_properties["execution_receipt"]["$ref"].endswith(
        "/ExecutionReceipt"
    )
