"""Deterministic v1 household translation tests."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError
import pytest

from policyengine_api.services.v2.households.transformations import (
    LEGACY_COLLECTION_NAMES,
    legacy_household_fingerprint,
    translate_legacy_household,
)
from policyengine_api.services.v2.households.types import LegacyHouseholdSnapshot
from policyengine_api.services.v2.households.validators import (
    LegacyHouseholdTranslationError,
)


DATA = Path(__file__).parents[2] / "data"


def _snapshot(country_id: str = "us", **changes: object) -> LegacyHouseholdSnapshot:
    fields: dict[str, object] = {
        "country_id": country_id,
        "legacy_household_id": 42,
        "label": "Presentation only",
        "api_version": "1.0.0",
        "household_json": {
            "people": {
                "adult": {"age": {"2026": 40}},
                "child": {"age": {"2026": 10}},
            },
            "households": {"home": {"members": ["adult", "child"]}},
            "families": {"family": {"members": ["adult", "child"]}},
            "tax_units": {"tax unit": {"members": ["adult", "child"]}},
            "spm_units": {"spm unit": {"members": ["adult", "child"]}},
            "marital_units": {
                "adult unit": {"members": ["adult"]},
                "child unit": {"members": ["child"]},
            },
        },
        "source_household_hash": "legacy/base64+hash=",
    }
    fields.update(changes)
    return LegacyHouseholdSnapshot.model_validate(fields)


@pytest.mark.parametrize("country_id", ["us", "uk"])
def test_representative_country_fixture_translates_all_entities(
    country_id: str,
) -> None:
    source = json.loads((DATA / f"{country_id}_household.json").read_text())
    translated = translate_legacy_household(
        _snapshot(country_id, household_json=source)
    )

    assert translated.default_year == 2023
    assert len(translated.household_data["people"]) == len(source["people"])
    for collection, records in translated.household_data.items():
        if collection != "people":
            source_collection = LEGACY_COLLECTION_NAMES[collection]
            assert len(records) == len(source[source_collection])


def test_multiple_groups_keep_stable_ids_names_values_and_relationships() -> None:
    translated = translate_legacy_household(_snapshot())
    people = translated.household_data["people"]
    marital_units = translated.household_data["marital_unit"]

    assert [person["source_name"] for person in people] == ["adult", "child"]
    assert [person["id"] for person in people] == ["person-1", "person-2"]
    assert [item["source_name"] for item in marital_units] == [
        "adult unit",
        "child unit",
    ]
    assert people[0]["memberships"]["marital_unit"] == "marital_unit-1"
    assert people[1]["memberships"]["marital_unit"] == "marital_unit-2"
    assert people[0]["values"]["age"] == {"2026": 40}


def test_array_variable_that_contains_person_names_is_not_a_relationship() -> None:
    source = _snapshot().household_json
    assert isinstance(source, dict)
    source["households"]["home"]["selected_people"] = ["adult", "child"]

    translated = translate_legacy_household(_snapshot(household_json=source))

    assert translated.household_data["household"][0]["values"]["selected_people"] == [
        "adult",
        "child",
    ]


def test_one_unambiguous_year_supplies_scalar_period_context() -> None:
    source = _snapshot().household_json
    assert isinstance(source, dict)
    source["people"]["adult"]["is_adult"] = True

    assert (
        translate_legacy_household(_snapshot(household_json=source)).default_year
        == 2026
    )


def test_several_explicit_years_produce_null_default_year() -> None:
    source = _snapshot().household_json
    assert isinstance(source, dict)
    source["people"]["adult"]["age"] = {"2025": 39, "2026": 40}

    translated = translate_legacy_household(_snapshot(household_json=source))

    assert translated.default_year is None
    assert translated.household_data["people"][0]["values"]["age"] == {
        "2025": 39,
        "2026": 40,
    }


def test_scalar_without_one_source_year_is_rejected() -> None:
    source = _snapshot().household_json
    assert isinstance(source, dict)
    source["people"]["adult"]["age"] = {"2025": 39, "2026": 40}
    source["people"]["child"]["is_child"] = True

    with pytest.raises(LegacyHouseholdTranslationError, match="unambiguous"):
        translate_legacy_household(_snapshot(household_json=source))


@pytest.mark.parametrize(
    "household_json",
    [
        {"people": {"adult": {}}, "households": {"home": {"members": ["absent"]}}},
        {"people": [], "households": {}},
        {"people": {}, "unsupported_entities": {}},
    ],
)
def test_invalid_or_lossy_source_is_rejected(household_json: object) -> None:
    with pytest.raises(LegacyHouseholdTranslationError):
        translate_legacy_household(_snapshot(household_json=household_json))


def test_complete_source_fingerprint_includes_identity_provenance_and_label() -> None:
    original = legacy_household_fingerprint(_snapshot())
    alternatives = [
        _snapshot(legacy_household_id=43),
        _snapshot(label="Another label"),
        _snapshot(api_version="2.0.0"),
        _snapshot(source_household_hash="another-source-hash"),
    ]

    assert all(legacy_household_fingerprint(item) != original for item in alternatives)
    assert translate_legacy_household(_snapshot(label="First")) == (
        translate_legacy_household(_snapshot(label="Second", legacy_household_id=43))
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"legacy_household_id": -1},
        {"api_version": ""},
        {"source_household_hash": ""},
        {"household_json": ["not", "an", "object"]},
        {"household_json": {"people": {"adult": {"age": float("nan")}}}},
    ],
)
def test_snapshot_rejects_incomplete_or_non_json_fields(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        _snapshot(**changes)
