"""Pin each structural failure of v2 household documents and v1 translation.

Each failure has its message and a fixed ``reason``. Copy failure logs record
the reason, never the message, which can hold a household's names and values.
"""

from __future__ import annotations

import copy
import pickle
import re

import pytest

from policyengine_api.services.v2.households.transformations import (
    translate_legacy_household,
)
from policyengine_api.services.v2.households.types import LegacyHouseholdSnapshot
from policyengine_api.services.v2.households.validators import (
    MAXIMUM_HOUSEHOLD_ENTITIES,
    MAXIMUM_HOUSEHOLD_RECORD_VALUES,
    HouseholdValidationError,
    HouseholdValidationReason,
    LegacyHouseholdTranslationError,
    LegacyHouseholdTranslationReason,
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
    ("country_id", "document", "message", "reason"),
    [
        ("fr", _uk_document(), "unsupported country_id 'fr'", "unsupported_country"),
        ("uk", [], "household_data must be an object", "document_not_object"),
        (
            "uk",
            _uk_document(spm={}),
            "household_data contains unsupported collections: ['spm']",
            "unsupported_collections",
        ),
        (
            "uk",
            {"household": [], "benunit": []},
            "household_data must contain people",
            "people_missing",
        ),
        ("us", {"people": [], "spm": []}, "spm must be an object", "spm_not_object"),
        (
            "us",
            {"people": [], "spm": {"unknown": 1}},
            "spm selection is invalid",
            "spm_selection_invalid",
        ),
        (
            "uk",
            _uk_document(household={}),
            "household must be a list",
            "collection_not_list",
        ),
        (
            "uk",
            _uk_document(
                household=[
                    {"id": f"household-{index}", "values": {}}
                    for index in range(MAXIMUM_HOUSEHOLD_ENTITIES + 1)
                ]
            ),
            f"household must contain at most {MAXIMUM_HOUSEHOLD_ENTITIES} records",
            "too_many_records",
        ),
        (
            "uk",
            _uk_document(
                household=[
                    {"id": "household-1", "values": {}},
                    {"id": "household-1", "values": {}},
                ]
            ),
            "household contains duplicate id 'household-1'",
            "duplicate_record_id",
        ),
        (
            "uk",
            _uk_document(people=["person-1"]),
            "people records must be objects",
            "record_not_object",
        ),
        (
            "uk",
            _uk_document(household=[{"id": "household-1", "colour": "blue"}]),
            "household record fields are invalid: missing=['values'], "
            "unsupported=['colour']",
            "record_fields_invalid",
        ),
        (
            "uk",
            _uk_document(household=[{"id": " ", "values": {}}]),
            "household id must be a non-empty string of at most 255 characters",
            "invalid_identifier",
        ),
        (
            "uk",
            _uk_document(household=[{"id": "h" * 256, "values": {}}]),
            "household id must be a non-empty string of at most 255 characters",
            "invalid_identifier",
        ),
        (
            "uk",
            _uk_document(
                household=[{"id": "household-1", "source_name": "", "values": {}}]
            ),
            "household source_name must be a non-empty string of at most 255 "
            "characters",
            "invalid_identifier",
        ),
        (
            "uk",
            _uk_document(household=[{"id": "household-1", "values": []}]),
            "household record values must be an object",
            "values_not_object",
        ),
        (
            "uk",
            _uk_document(
                household=[
                    {
                        "id": "household-1",
                        "values": {
                            f"variable_{index}": index
                            for index in range(MAXIMUM_HOUSEHOLD_RECORD_VALUES + 1)
                        },
                    }
                ]
            ),
            f"household records must contain at most "
            f"{MAXIMUM_HOUSEHOLD_RECORD_VALUES} variable values",
            "too_many_values",
        ),
        (
            "uk",
            _uk_document(people=[{**UK_PERSON, "memberships": []}]),
            "people record memberships must be an object",
            "memberships_not_object",
        ),
        (
            "uk",
            _uk_document(
                people=[{**UK_PERSON, "memberships": {"household": "household-1"}}]
            ),
            "people record memberships must identify every country-supported "
            "entity collection",
            "incomplete_memberships",
        ),
        (
            "uk",
            _uk_document(
                people=[{**UK_PERSON, "memberships": {"household": 1, "benunit": "b"}}]
            ),
            "person household membership must be a non-empty string of at most 255 "
            "characters",
            "invalid_identifier",
        ),
        (
            "uk",
            _uk_document(
                people=[
                    {
                        **UK_PERSON,
                        "memberships": {
                            "household": "household-1",
                            "benunit": "benunit-2",
                        },
                    }
                ]
            ),
            "person membership references absent benunit id 'benunit-2'",
            "absent_membership_target",
        ),
    ],
)
def test_invalid_documents_fail_with_their_specific_message_and_reason(
    country_id: str,
    document: object,
    message: str,
    reason: str,
) -> None:
    """Each rule has its own message and a fixed reason that logs can record."""
    with pytest.raises(
        HouseholdValidationError, match=rf"^{re.escape(message)}$"
    ) as raised:
        normalize_household_document(country_id, document)
    assert raised.value.reason == reason


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


def _snapshot(
    household_json: object, *, country_id: str = "uk"
) -> LegacyHouseholdSnapshot:
    return LegacyHouseholdSnapshot.model_construct(
        country_id=country_id,
        legacy_household_id=42,
        label=None,
        api_version="1.0.0",
        household_json=household_json,
        source_household_hash="legacy/base64+hash=",
    )


@pytest.mark.parametrize(
    ("household_json", "message", "reason"),
    [
        (
            {"people": {}, "households": {}, "families": {}},
            "legacy household contains unsupported collections: ['families']",
            "legacy_unsupported_collections",
        ),
        (
            {"people": []},
            "legacy people must be an object",
            "legacy_people_not_object",
        ),
        (
            {"people": {}, "benunits": []},
            "legacy benunits must be an object",
            "legacy_groups_not_object",
        ),
        (
            {"people": {}, "households": {"home": []}},
            "legacy households records must be objects",
            "legacy_group_not_object",
        ),
        (
            {"people": {"adult": {}}, "households": {"home": {"members": "adult"}}},
            "legacy households members must reference named people",
            "legacy_members_not_named_people",
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
            "legacy_person_in_multiple_groups",
        ),
        (
            {"people": {"adult": []}},
            "legacy person records must be objects",
            "legacy_person_not_object",
        ),
        (
            {
                "people": {"adult": {"age": {"2026": 40, "2027": 41}}},
                "households": {"home": {"members": ["adult"], "rent": 1}},
                "benunits": {"unit": {"members": ["adult"]}},
            },
            "legacy household has values without explicit periods and no "
            "unambiguous default year",
            "legacy_ambiguous_default_year",
        ),
        (
            {"people": {"a" * 256: {}}},
            "people source_name must be a non-empty string of at most 255 characters",
            "invalid_identifier",
        ),
        (
            # A person in no benunit, as some v1 households leave people out
            # of a group collection: the translated document breaks the v2
            # rule that every person belongs to one record of each.
            {
                "people": {"adult": {"age": {"2026": 40}}},
                "households": {"home": {"members": ["adult"]}},
            },
            "people record memberships must identify every country-supported "
            "entity collection",
            "incomplete_memberships",
        ),
        (
            {
                "people": {"adult": {"age": {"2026": float("inf")}}},
                "households": {"home": {"members": ["adult"]}},
                "benunits": {"unit": {"members": ["adult"]}},
            },
            "JSON numbers must be finite",
            "value_not_json",
        ),
    ],
)
def test_untranslatable_v1_documents_fail_with_their_specific_message_and_reason(
    household_json: dict[str, object],
    message: str,
    reason: str,
) -> None:
    """Each failure has its own message and a fixed reason that logs can record.

    A translation whose result breaks a v2 document rule takes that rule's
    reason.
    """
    with pytest.raises(
        LegacyHouseholdTranslationError, match=rf"^{re.escape(message)}$"
    ) as raised:
        translate_legacy_household(_snapshot(household_json))
    assert raised.value.reason == reason


def _uk_household_of(people: dict[str, object]) -> dict[str, object]:
    """Return a v1 UK household with every person in one household and benunit."""
    return {
        "people": people,
        "households": {"home": {"members": list(people)}},
        "benunits": {"unit": {"members": list(people)}},
    }


@pytest.mark.parametrize(
    ("country_id", "household_json", "message", "reason"),
    [
        (
            "uk",
            _uk_household_of(
                {
                    f"person {index}": {"age": {"2026": 40}}
                    for index in range(MAXIMUM_HOUSEHOLD_ENTITIES + 1)
                }
            ),
            f"people must contain at most {MAXIMUM_HOUSEHOLD_ENTITIES} records",
            "too_many_records",
        ),
        (
            "uk",
            _uk_household_of(
                {
                    "adult": {
                        f"variable_{index}": {"2026": index}
                        for index in range(MAXIMUM_HOUSEHOLD_RECORD_VALUES + 1)
                    }
                }
            ),
            f"people records must contain at most "
            f"{MAXIMUM_HOUSEHOLD_RECORD_VALUES} variable values",
            "too_many_values",
        ),
        (
            "uk",
            _uk_household_of({" ": {"age": {"2026": 40}}}),
            "people source_name must be a non-empty string of at most 255 characters",
            "invalid_identifier",
        ),
        ("us", {"people": {}, "spm": []}, "spm must be an object", "spm_not_object"),
        (
            "us",
            {"people": {}, "spm": {"unknown": 1}},
            "spm selection is invalid",
            "spm_selection_invalid",
        ),
    ],
)
def test_v1_households_breaking_a_v2_limit_take_its_reason(
    country_id: str,
    household_json: dict[str, object],
    message: str,
    reason: str,
) -> None:
    """A v1 household can break these v2 rules: its size, names and SPM selection.

    The translation builds the rest of the v2 document itself.
    """
    with pytest.raises(
        LegacyHouseholdTranslationError, match=rf"^{re.escape(message)}$"
    ) as raised:
        translate_legacy_household(_snapshot(household_json, country_id=country_id))
    assert raised.value.reason == reason


@pytest.mark.parametrize(
    "error",
    [
        HouseholdValidationError(
            "people must be a list",
            reason=HouseholdValidationReason.COLLECTION_NOT_LIST,
        ),
        LegacyHouseholdTranslationError(
            "legacy people must be an object",
            reason=LegacyHouseholdTranslationReason.PEOPLE_NOT_OBJECT,
        ),
        LegacyHouseholdTranslationError(
            "people record memberships must identify every country-supported "
            "entity collection",
            reason=HouseholdValidationReason.INCOMPLETE_MEMBERSHIPS,
        ),
    ],
)
def test_errors_keep_their_message_and_reason_when_copied_or_pickled(
    error: HouseholdValidationError | LegacyHouseholdTranslationError,
) -> None:
    rebuilt_errors = [
        copy.copy(error),
        copy.deepcopy(error),
        pickle.loads(pickle.dumps(error)),  # noqa: S301  # round-trips an error this test built
    ]

    for rebuilt in rebuilt_errors:
        assert type(rebuilt) is type(error)
        assert str(rebuilt) == str(error)
        assert rebuilt.reason == error.reason


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
