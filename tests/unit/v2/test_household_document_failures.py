"""Pin each structural failure of v2 household documents and v1 translation."""

from __future__ import annotations

import re

import pytest

from policyengine_api.services.v2.households.transformations import (
    translate_legacy_household,
)
from policyengine_api.services.v2.households.types import LegacyHouseholdSnapshot
from policyengine_api.services.v2.households.validators import (
    HouseholdValidationError,
    LegacyHouseholdTranslationError,
    normalize_household_document,
    require_json_value,
)
from policyengine_api.services.v2.policies.validators import (
    require_json_value as require_policy_json_value,
)

UK_PERSON = {
    "id": "person-1",
    "values": {"age": {"2026": 40}},
    "memberships": {"household": "household-1", "benunit": "benunit-1"},
}


def _uk_document(**changes: object) -> dict[str, object]:
    document: dict[str, object] = {
        "people": [dict(UK_PERSON)],
        "household": [{"id": "household-1", "values": {}}],
        "benunit": [{"id": "benunit-1", "values": {}}],
    }
    document.update(changes)
    return document


@pytest.mark.parametrize(
    ("country_id", "document", "message"),
    [
        ("fr", _uk_document(), "unsupported country_id 'fr'"),
        ("uk", [], "household_data must be an object"),
        (
            "uk",
            _uk_document(spm={}),
            "household_data contains unsupported collections: ['spm']",
        ),
        ("uk", {"household": [], "benunit": []}, "household_data must contain people"),
        ("us", {"people": [], "spm": []}, "spm must be an object"),
        ("us", {"people": [], "spm": {"unknown": 1}}, "spm selection is invalid"),
        ("uk", _uk_document(household={}), "household must be a list"),
        ("uk", _uk_document(people=["person-1"]), "people records must be objects"),
        (
            "uk",
            _uk_document(household=[{"id": "household-1", "colour": "blue"}]),
            "household record fields are invalid: missing=['values'], "
            "unsupported=['colour']",
        ),
        (
            "uk",
            _uk_document(household=[{"id": " ", "values": {}}]),
            "household id must be a non-empty string of at most 255 characters",
        ),
        (
            "uk",
            _uk_document(household=[{"id": "h" * 256, "values": {}}]),
            "household id must be a non-empty string of at most 255 characters",
        ),
        (
            "uk",
            _uk_document(
                household=[{"id": "household-1", "source_name": "", "values": {}}]
            ),
            "household source_name must be a non-empty string of at most 255 "
            "characters",
        ),
        (
            "uk",
            _uk_document(household=[{"id": "household-1", "values": []}]),
            "household record values must be an object",
        ),
        (
            "uk",
            _uk_document(people=[{**UK_PERSON, "memberships": []}]),
            "people record memberships must be an object",
        ),
        (
            "uk",
            _uk_document(
                people=[{**UK_PERSON, "memberships": {"household": 1, "benunit": "b"}}]
            ),
            "person household membership must be a non-empty string of at most 255 "
            "characters",
        ),
    ],
)
def test_invalid_documents_fail_with_their_specific_message(
    country_id: str,
    document: object,
    message: str,
) -> None:
    with pytest.raises(HouseholdValidationError, match=rf"^{re.escape(message)}$"):
        normalize_household_document(country_id, document)


def test_normalized_documents_list_spm_first_then_people_and_entities() -> None:
    document = {
        "family": [],
        "tax_unit": [],
        "spm_unit": [],
        "marital_unit": [],
        "household": [],
        "people": [],
        "spm": {},
    }

    normalized = normalize_household_document("us", document)

    assert list(normalized) == [
        "spm",
        "people",
        "household",
        "family",
        "tax_unit",
        "spm_unit",
        "marital_unit",
    ]


@pytest.mark.parametrize(
    "require_value", [require_json_value, require_policy_json_value]
)
def test_json_values_reject_deep_nesting_and_reference_cycles(require_value) -> None:
    nested: list[object] = []
    deepest = nested
    for _ in range(101):
        child: list[object] = []
        deepest.append(child)
        deepest = child
    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic

    with pytest.raises(
        ValueError, match=r"^JSON values must not exceed 100 nested containers$"
    ):
        require_value(nested)
    with pytest.raises(
        ValueError, match=r"^JSON values must not contain reference cycles$"
    ):
        require_value(cyclic)
    with pytest.raises(ValueError, match=r"^JSON numbers must be finite$"):
        require_value([float("inf")])
    with pytest.raises(
        ValueError, match=r"^value must contain only standards-compliant JSON types$"
    ):
        require_value({"value": (1,)})
    with pytest.raises(ValueError, match=r"^JSON object keys must be strings$"):
        require_value({1: "one"})
    shared = [1.5]
    document = {"first": shared, "second": [shared, None, True, "text", 3]}
    assert require_value(document) is document


def _snapshot(household_json: object) -> LegacyHouseholdSnapshot:
    return LegacyHouseholdSnapshot.model_construct(
        country_id="uk",
        legacy_household_id=42,
        label=None,
        api_version="1.0.0",
        household_json=household_json,
        source_household_hash="legacy/base64+hash=",
    )


@pytest.mark.parametrize(
    ("household_json", "message"),
    [
        (
            {"people": {}, "households": {}, "families": {}},
            "legacy household contains unsupported collections: ['families']",
        ),
        ({"people": []}, "legacy people must be an object"),
        ({"people": {}, "benunits": []}, "legacy benunits must be an object"),
        (
            {"people": {}, "households": {"home": []}},
            "legacy households records must be objects",
        ),
        (
            {"people": {"adult": {}}, "households": {"home": {"members": "adult"}}},
            "legacy households members must reference named people",
        ),
        (
            {
                "people": {"adult": {}},
                "benunits": {
                    "first": {"members": ["adult"]},
                    "second": {"members": ["adult"]},
                },
            },
            "legacy person 'adult' belongs to multiple benunits records",
        ),
        ({"people": {"adult": []}}, "legacy person records must be objects"),
        (
            {"people": {"a" * 256: {}}},
            "people source_name must be a non-empty string of at most 255 characters",
        ),
    ],
)
def test_untranslatable_v1_documents_fail_with_their_specific_message(
    household_json: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(
        LegacyHouseholdTranslationError, match=rf"^{re.escape(message)}$"
    ):
        translate_legacy_household(_snapshot(household_json))


def test_non_object_v1_document_is_a_type_error() -> None:
    with pytest.raises(TypeError, match=r"^legacy household_json must be an object$"):
        translate_legacy_household(_snapshot(["people"]))


def test_repeated_membership_in_one_group_translates_once() -> None:
    translated = translate_legacy_household(
        _snapshot(
            {
                "people": {"adult": {"age": {"2026": 40}}},
                "households": {"home": {"members": ["adult", "adult"]}},
                "benunits": {"unit": {"members": ["adult"], "rent": {"2026": 1}}},
            }
        )
    )

    assert translated.default_year == 2026
    assert translated.household_data == {
        "people": [
            {
                "id": "person-1",
                "source_name": "adult",
                "values": {"age": {"2026": 40}},
                "memberships": {"household": "household-1", "benunit": "benunit-1"},
            }
        ],
        "household": [{"id": "household-1", "source_name": "home", "values": {}}],
        "benunit": [
            {
                "id": "benunit-1",
                "source_name": "unit",
                "values": {"rent": {"2026": 1}},
            }
        ],
    }
