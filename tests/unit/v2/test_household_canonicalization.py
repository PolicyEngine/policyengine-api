"""Deterministic canonical household-content tests."""

from __future__ import annotations

import hashlib

from policyengine_api.services.v2.households.transformations import (
    HOUSEHOLD_CANONICALIZATION_VERSION,
    canonical_household_document,
    canonicalize_household,
)
from policyengine_api.services.v2.households.types import HouseholdCreationInput


def _command(*, people=None, default_year=2026) -> HouseholdCreationInput:
    return HouseholdCreationInput.model_validate(
        {
            "country_id": "us",
            "default_year": default_year,
            "household_data": {
                "people": people
                if people is not None
                else [
                    {
                        "id": "person-2",
                        "source_name": "Second",
                        "values": {"array": [3, 2, 1], "rate": 1},
                        "memberships": {},
                    },
                    {
                        "id": "person-1",
                        "source_name": "First",
                        "values": {"enabled": True},
                        "memberships": {},
                    },
                ],
                "household": [],
                "family": [],
                "tax_unit": [],
                "spm_unit": [],
                "marital_unit": [],
            },
        }
    )


def test_document_has_versioned_deterministic_content_only() -> None:
    document = canonical_household_document(_command())

    assert document.startswith(
        b'{"canonicalization_version":1,"country_id":"us","default_year":2026,'
    )
    assert document.index(b'"id":"person-1"') < document.index(b'"id":"person-2"')
    assert b"created_at" not in document
    assert b"legacy_household_id" not in document
    assert b"api_version" not in document
    assert b"label" not in document
    assert b"description" not in document


def test_entity_and_object_member_order_do_not_change_identity() -> None:
    original = _command()
    reordered = _command(
        people=[
            {
                "memberships": {},
                "values": {"rate": 1.0, "array": [3, 2, 1]},
                "source_name": "Second",
                "id": "person-2",
            },
            {
                "memberships": {},
                "values": {"enabled": True},
                "source_name": "First",
                "id": "person-1",
            },
        ]
    )

    assert canonicalize_household(original) == canonicalize_household(reordered)


def test_meaningful_array_order_changes_identity() -> None:
    changed = _command()
    changed.household_data["people"][0]["values"]["array"] = [1, 2, 3]

    assert canonicalize_household(_command()) != canonicalize_household(changed)


def test_country_default_year_membership_and_values_are_material_content() -> None:
    original = canonical_household_document(_command())
    changed_year = canonical_household_document(_command(default_year=2027))
    changed_people = _command()
    changed_people.household_data["people"][0]["memberships"] = {
        "household": "household-1"
    }
    changed_value = _command()
    changed_value.household_data["people"][0]["values"]["rate"] = 2

    assert changed_year != original
    assert canonical_household_document(changed_people) != original
    assert canonical_household_document(changed_value) != original


def test_digest_is_sha256_of_exact_canonical_bytes() -> None:
    content = canonicalize_household(_command())

    assert content.version == HOUSEHOLD_CANONICALIZATION_VERSION
    assert content.content_hash == hashlib.sha256(content.document).hexdigest()
    assert len(content.content_hash) == 64
