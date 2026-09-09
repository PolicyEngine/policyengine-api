"""Validation tests for immutable API v2 household inputs."""

from __future__ import annotations

from pydantic import ValidationError
import pytest

from policyengine_api.services.v2.households.services import normalize_creation_input
from policyengine_api.services.v2.households.types import (
    HouseholdCreationInput,
    NativeHouseholdCreationInput,
)
from policyengine_api.services.v2.households.validators import (
    MAXIMUM_HOUSEHOLD_ENTITIES,
    MAXIMUM_HOUSEHOLD_RECORD_VALUES,
    HouseholdValidationError,
)


def _us_document() -> dict[str, object]:
    memberships = {
        "household": "household-1",
        "family": "family-1",
        "tax_unit": "tax-unit-1",
        "spm_unit": "spm-unit-1",
        "marital_unit": "marital-unit-1",
    }
    document: dict[str, object] = {
        "people": [
            {
                "id": "person-1",
                "values": {"age": {"2026": 40}},
                "memberships": memberships,
            }
        ]
    }
    for collection, identifier in memberships.items():
        document[collection] = [{"id": identifier, "values": {}}]
    return document


def _native(**changes: object) -> dict[str, object]:
    result: dict[str, object] = {
        "country_id": "US",
        "default_year": 2026,
        "household_data": _us_document(),
    }
    result.update(changes)
    return result


def test_native_input_requires_a_bounded_default_year() -> None:
    assert NativeHouseholdCreationInput.model_validate(_native()).country_id == "us"

    for value in (None, 1899, 2201):
        with pytest.raises(ValidationError):
            NativeHouseholdCreationInput.model_validate(_native(default_year=value))
    missing = _native()
    del missing["default_year"]
    with pytest.raises(ValidationError):
        NativeHouseholdCreationInput.model_validate(missing)


def test_legacy_creation_type_is_the_only_input_that_permits_null_year() -> None:
    parsed = HouseholdCreationInput.model_validate(_native(default_year=None))

    assert parsed.default_year is None


def test_us_document_validates_references_and_normalizes_supported_collections() -> (
    None
):
    household_input = HouseholdCreationInput.model_validate(_native())
    normalized = normalize_creation_input(household_input)

    assert set(normalized.household_data) == {
        "people",
        "household",
        "family",
        "tax_unit",
        "spm_unit",
        "marital_unit",
    }


def test_uk_document_uses_the_uk_entity_contract() -> None:
    parsed = HouseholdCreationInput.model_validate(
        {
            "country_id": "uk",
            "default_year": 2026,
            "household_data": {
                "people": [
                    {
                        "id": "person-1",
                        "values": {"age": 40},
                        "memberships": {
                            "household": "household-1",
                            "benunit": "benunit-1",
                        },
                    }
                ],
                "household": [{"id": "household-1", "values": {}}],
                "benunit": [{"id": "benunit-1", "values": {}}],
            },
        }
    )

    assert set(normalize_creation_input(parsed).household_data) == {
        "people",
        "household",
        "benunit",
    }


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda document: document["people"].append(document["people"][0].copy()),
            "duplicate id",
        ),
        (
            lambda document: document["people"][0]["memberships"].update(
                {"household": "absent"}
            ),
            "references absent",
        ),
        (
            lambda document: document.update({"benunit": []}),
            "unsupported collections",
        ),
        (
            lambda document: document["people"][0]["memberships"].pop("family"),
            "identify every",
        ),
    ],
)
def test_invalid_identity_relationship_and_country_structure_is_rejected(
    mutate, message: str
) -> None:
    document = _us_document()
    mutate(document)
    household_input = HouseholdCreationInput.model_validate(
        _native(household_data=document)
    )

    with pytest.raises(HouseholdValidationError, match=message):
        normalize_creation_input(household_input)


def test_entity_and_record_value_limits_are_enforced() -> None:
    document = _us_document()
    document["people"] = [
        {
            "id": f"person-{index}",
            "values": {},
            "memberships": {
                "household": "household-1",
                "family": "family-1",
                "tax_unit": "tax-unit-1",
                "spm_unit": "spm-unit-1",
                "marital_unit": "marital-unit-1",
            },
        }
        for index in range(MAXIMUM_HOUSEHOLD_ENTITIES + 1)
    ]
    too_many_entities = HouseholdCreationInput.model_validate(
        _native(household_data=document)
    )
    with pytest.raises(HouseholdValidationError, match="at most 1000"):
        normalize_creation_input(too_many_entities)

    document = _us_document()
    document["people"][0]["values"] = {
        f"variable_{index}": index
        for index in range(MAXIMUM_HOUSEHOLD_RECORD_VALUES + 1)
    }
    too_many_values = HouseholdCreationInput.model_validate(
        _native(household_data=document)
    )
    with pytest.raises(HouseholdValidationError, match="at most 500"):
        normalize_creation_input(too_many_values)


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), {1: "non-string key"}, ("tuple",), object()],
)
def test_non_json_values_are_rejected(value: object) -> None:
    document = _us_document()
    document["people"][0]["values"] = {"invalid": value}

    with pytest.raises(ValidationError):
        HouseholdCreationInput.model_validate(_native(household_data=document))


def test_variable_names_are_not_checked_against_a_model_catalog() -> None:
    document = _us_document()
    document["people"][0]["values"] = {
        "future_variable_not_in_current_catalog": {
            "2026": {"scalar": 1, "array": [3, 2, 1]}
        }
    }
    parsed = HouseholdCreationInput.model_validate(_native(household_data=document))

    assert normalize_creation_input(parsed).household_data == document


@pytest.mark.parametrize(
    "selection",
    [
        {"geography_kind": "national"},
        {
            "forecast_content_sha256": "a" * 64,
            "scenario": "baseline",
            "geography_kind": "metro",
            "geography_id": "31080",
            "county_vintage": "2020",
            "as_of": "2026-09-09",
        },
    ],
)
def test_spm_input_is_structurally_validated_without_resolving_omissions(
    selection,
) -> None:
    document = _us_document()
    document["spm"] = selection
    parsed = HouseholdCreationInput.model_validate(_native(household_data=document))
    assert normalize_creation_input(parsed).household_data == document


@pytest.mark.parametrize(
    "selection",
    [None, [], "national", {"unexpected": True}, {"geography_kind": "metro"}],
)
def test_invalid_spm_input_is_rejected(selection) -> None:
    document = _us_document()
    document["spm"] = selection
    parsed = HouseholdCreationInput.model_validate(_native(household_data=document))
    with pytest.raises(HouseholdValidationError):
        normalize_creation_input(parsed)


def test_uk_input_rejects_us_only_spm() -> None:
    parsed = HouseholdCreationInput.model_validate(
        {
            "country_id": "uk",
            "default_year": 2026,
            "household_data": {
                "people": [],
                "household": [],
                "benunit": [],
                "spm": {"geography_kind": "national"},
            },
        }
    )
    with pytest.raises(HouseholdValidationError):
        normalize_creation_input(parsed)
