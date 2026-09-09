"""Unit checks for conflict-aware household insertion statements."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import Mock
from uuid import uuid4

from sqlalchemy.dialects import postgresql
import pytest

from policyengine_api.data.v2.models import Household, LegacyHouseholdMapping
from policyengine_api.services.v2.households.database_connectors import creates
from policyengine_api.services.v2.households.services import (
    create_normalized_household,
    mirror_legacy_household_in_session,
)
from policyengine_api.services.v2.households.transformations import (
    canonicalize_household,
    legacy_household_fingerprint,
)
from policyengine_api.services.v2.households.types import (
    HouseholdCreationInput,
    LegacyHouseholdSnapshot,
)
from policyengine_api.services.v2.households.validators import (
    HouseholdContentHashCollisionError,
    LegacyHouseholdMappingIntegrityError,
)


def _input() -> HouseholdCreationInput:
    return HouseholdCreationInput.model_validate(
        {
            "country_id": "us",
            "default_year": 2026,
            "household_data": {
                "people": [],
                "household": [],
                "family": [],
                "tax_unit": [],
                "spm_unit": [],
                "marital_unit": [],
            },
        }
    )


def _snapshot(**changes: object) -> LegacyHouseholdSnapshot:
    fields: dict[str, object] = {
        "country_id": "us",
        "legacy_household_id": 42,
        "label": None,
        "api_version": "1.0.0",
        "household_json": {"people": {}},
        "source_household_hash": "source-hash",
    }
    fields.update(changes)
    return LegacyHouseholdSnapshot.model_validate(fields)


def test_household_insert_uses_content_identity_conflict_and_returning() -> None:
    source = " ".join(
        str(value) for value in creates.create_household.__code__.co_consts
    )
    assert "uq_households_canonicalization_content_hash" in source

    statement = (
        creates.insert(creates.Household)
        .on_conflict_do_nothing(
            constraint="uq_households_canonicalization_content_hash"
        )
        .returning(creates.Household.id)
    )
    compiled = str(statement.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT ON CONSTRAINT" in compiled
    assert "DO NOTHING" in compiled
    assert "RETURNING households.id" in compiled


def test_hash_conflict_reuses_only_byte_equal_stored_content(monkeypatch) -> None:
    household_input = _input()
    content = canonicalize_household(household_input)
    stored = Household(
        country_id="us",
        default_year=2026,
        household_data=household_input.household_data,
        canonicalization_version=content.version,
        content_hash=content.content_hash,
    )
    monkeypatch.setattr(
        "policyengine_api.services.v2.households.services.create_household",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "policyengine_api.services.v2.households.services.read_household_by_content_identity",
        lambda *_args, **_kwargs: stored,
    )

    result = create_normalized_household(Mock(), household_input)
    assert result.household_id == stored.id
    assert result.created is False

    collision = replace(content, document=b"different canonical bytes")
    with pytest.raises(HouseholdContentHashCollisionError):
        create_normalized_household(
            Mock(), household_input, canonicalizer=lambda _input: collision
        )


def test_existing_legacy_mapping_is_verified_without_insertion(monkeypatch) -> None:
    snapshot = _snapshot()
    translated = _input().model_copy(update={"default_year": None})
    destination_id = uuid4()
    mapping = LegacyHouseholdMapping(
        country_id="us",
        legacy_household_id=42,
        household_id=destination_id,
        source_api_version="1.0.0",
        fingerprint_version=1,
        fingerprint_sha256=legacy_household_fingerprint(snapshot),
    )
    create_mapping = Mock()
    monkeypatch.setattr(
        "policyengine_api.services.v2.households.services.read_legacy_household_mapping",
        lambda *_args, **_kwargs: mapping,
    )
    monkeypatch.setattr(
        "policyengine_api.services.v2.households.services.translate_legacy_household",
        lambda _snapshot: translated,
    )
    monkeypatch.setattr(
        "policyengine_api.services.v2.households.services.create_normalized_household",
        lambda *_args, **_kwargs: type(
            "Result", (), {"household_id": destination_id, "created": False}
        )(),
    )
    monkeypatch.setattr(
        "policyengine_api.services.v2.households.services.create_legacy_household_mapping",
        create_mapping,
    )

    result = mirror_legacy_household_in_session(Mock(), snapshot)

    assert result.household_id == destination_id
    assert result.mapping_created is False
    create_mapping.assert_not_called()


def test_changed_complete_source_fingerprint_fails_before_translation(
    monkeypatch,
) -> None:
    snapshot = _snapshot()
    mapping = LegacyHouseholdMapping(
        country_id="us",
        legacy_household_id=42,
        household_id=uuid4(),
        source_api_version="1.0.0",
        fingerprint_version=1,
        fingerprint_sha256="f" * 64,
    )
    translate = Mock()
    monkeypatch.setattr(
        "policyengine_api.services.v2.households.services.read_legacy_household_mapping",
        lambda *_args, **_kwargs: mapping,
    )
    monkeypatch.setattr(
        "policyengine_api.services.v2.households.services.translate_legacy_household",
        translate,
    )

    with pytest.raises(LegacyHouseholdMappingIntegrityError):
        mirror_legacy_household_in_session(Mock(), snapshot)
    translate.assert_not_called()
