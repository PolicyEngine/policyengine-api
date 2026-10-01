"""Compact canonical SPM provenance contracts."""

import json

import pytest
from pydantic import ValidationError

from policyengine_api.spm import (
    SPMComparisonProvenance,
    SPMProvenance,
    SPMRuntimeVersions,
    SPMSelection,
    build_spm_calculation_provenance,
    build_spm_comparison_provenance,
    build_spm_provenance,
    resolved_spm_configuration,
    validate_spm_calculation_provenance,
)


SHA256 = "a" * 64
SELECTION = SPMSelection.model_validate(
    {
        "forecast_content_sha256": SHA256,
        "scenario": "ce_trend",
        "geography_kind": "national",
        "geography_id": None,
        "county_vintage": "2020",
        "as_of": None,
    }
)
VERSIONS = SPMRuntimeVersions.model_validate(
    {
        "policyengine": "6.2.1",
        "policyengine-core": "3.32.10",
        "policyengine-us": "2.2.1",
        "spm-calculator": "1.0.0",
    }
)


def _receipt(**changes: object) -> SPMProvenance:
    values: dict[str, object] = {
        "forecast_id": "spm-rolling-2026-09-09",
        "forecast_sha256": SHA256,
        "selection": SELECTION,
        "years": ("2026",),
        "runtime_versions": VERSIONS,
    }
    values.update(changes)
    return build_spm_provenance(**values)


def test_compact_receipt_has_only_the_public_v2_fields() -> None:
    receipt = _receipt()

    assert receipt.model_dump(mode="json", by_alias=True) == {
        "schema_version": "canonical-spm-provenance-v2",
        "forecast_id": "spm-rolling-2026-09-09",
        "forecast_sha256": SHA256,
        "scenario": "ce_trend",
        "geography_kind": "national",
        "geography_id": None,
        "county_vintage": "2020",
        "as_of": None,
        "years": ["2026"],
        "runtime_versions": {
            "policyengine": "6.2.1",
            "policyengine-core": "3.32.10",
            "policyengine-us": "2.2.1",
            "spm-calculator": "1.0.0",
        },
    }
    assert len(receipt.model_dump_json(by_alias=True).encode()) < 1_024


@pytest.mark.parametrize(
    "changes",
    [
        {"forecast_sha256": "A" * 64},
        {"years": ("26",)},
        {"years": ("2027", "2026")},
        {"years": ("2026", "2026")},
    ],
)
def test_compact_receipt_rejects_noncanonical_values(
    changes: dict[str, object],
) -> None:
    with pytest.raises((ValidationError, ValueError)):
        _receipt(**changes)


@pytest.mark.parametrize(
    "invalid_version",
    ["policyengine", "policyengine-core", "policyengine-us", "spm-calculator"],
)
@pytest.mark.parametrize("value", [None, ""])
def test_runtime_versions_require_four_nonempty_strings(
    invalid_version: str,
    value: object,
) -> None:
    versions = VERSIONS.model_dump(mode="json", by_alias=True)
    versions[invalid_version] = value

    with pytest.raises(ValidationError):
        SPMRuntimeVersions.model_validate(versions)


def test_completed_calculation_contract_rejects_legacy_dual_field_shape() -> None:
    receipt = _receipt().model_dump(mode="json", by_alias=True)

    with pytest.raises(ValidationError):
        validate_spm_calculation_provenance(
            {
                "spm_config": SELECTION.model_dump(mode="json"),
                "spm_provenance": receipt,
            }
        )


def test_compact_receipt_rejects_the_previous_diagnostic_shape() -> None:
    previous = {
        "forecast_id": "spm-rolling-2026-09-09",
        "forecast_sha256": SHA256,
        "scenario": "ce_trend",
        "geography_kind": "national",
        "runtime_versions": {},
        "years": {"2026": {}},
        "geographies": [],
        "composition_method": "classified inputs",
        "storage_method": "formula",
    }

    with pytest.raises(ValidationError):
        SPMProvenance.model_validate(previous)


def test_country_receipt_adapter_extracts_only_compact_scalars() -> None:
    country_receipt: dict[str, object] = {
        "forecast_id": "spm-rolling-2026-09-09",
        "forecast_sha256": SHA256,
        "scenario": "ce_trend",
        "geography_kind": "national",
        "runtime_versions": VERSIONS.model_dump(mode="json", by_alias=True),
        "years": {"2027": {"large": "diagnostic"}, "2026": {}},
        "geographies": [{"large": "mapping"}],
        "composition_method": "classified inputs",
        "storage_method": "formula",
    }

    calculation = build_spm_calculation_provenance(SELECTION, country_receipt)

    assert resolved_spm_configuration(calculation).model_dump(
        mode="json"
    ) == SELECTION.model_dump(mode="json")
    assert calculation.years == ("2026", "2027")
    encoded = calculation.model_dump_json(by_alias=True)
    assert "diagnostic" not in encoded
    assert "mapping" not in encoded
    assert "composition_method" not in encoded


def test_country_receipt_must_agree_with_adjacent_configuration() -> None:
    country_receipt: dict[str, object] = {
        "forecast_id": "spm-rolling-2026-09-09",
        "forecast_sha256": SHA256,
        "scenario": "different",
        "geography_kind": "national",
        "runtime_versions": VERSIONS.model_dump(mode="json", by_alias=True),
        "years": {},
    }

    with pytest.raises(ValueError, match="differs from the SPM configuration"):
        build_spm_calculation_provenance(SELECTION, country_receipt)


def test_comparison_collapses_identical_child_receipts() -> None:
    receipt = _receipt()

    comparison = build_spm_comparison_provenance(
        baseline_receipts=(receipt,) * 20,
        reform_receipts=(receipt,) * 20,
    )

    assert comparison.baseline.receipt == receipt
    assert comparison.baseline.execution_count == 20
    assert comparison.reform.receipt == receipt
    assert comparison.reform.execution_count == 20
    assert len(comparison.model_dump_json(by_alias=True).encode()) < 2_048


@pytest.mark.parametrize("side", ["baseline", "reform"])
def test_comparison_rejects_inconsistent_child_receipts(side: str) -> None:
    receipt = _receipt()
    different = _receipt(years=("2027",))
    inputs = {
        "baseline_receipts": (receipt,),
        "reform_receipts": (receipt,),
    }
    inputs[f"{side}_receipts"] = (receipt, different)

    with pytest.raises(ValueError, match=f"{side} SPM receipts differ"):
        build_spm_comparison_provenance(**inputs)


def test_comparison_rejects_previous_list_shape() -> None:
    receipt = _receipt().model_dump(mode="json", by_alias=True)

    with pytest.raises(ValidationError):
        SPMComparisonProvenance.model_validate(
            {"baseline": [receipt], "reform": [receipt]}
        )


def test_compact_models_survive_json_round_trip() -> None:
    comparison = build_spm_comparison_provenance(
        baseline_receipts=(_receipt(),),
        reform_receipts=(_receipt(),),
    )

    assert (
        SPMComparisonProvenance.model_validate_json(
            json.dumps(comparison.model_dump(mode="json", by_alias=True))
        )
        == comparison
    )
