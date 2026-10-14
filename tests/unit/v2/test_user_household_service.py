"""Service tests for v2 user-household associations."""

from __future__ import annotations

import pytest
from sqlmodel import select

from policyengine_api.data.v2.models import Household, UserHouseholdAssociation
from policyengine_api.services.v2.legacy_refs.validators import (
    LegacyReferenceNotFoundError,
)
from policyengine_api.services.v2.user_households.database_session import (
    UserHouseholdDatabaseSession,
)
from policyengine_api.services.v2.user_households.services import (
    V2UserHouseholdService,
)
from policyengine_api.services.v2.user_households.types import (
    UserHouseholdCreateFields,
    UserHouseholdUpdateInput,
)
from policyengine_api.services.v2.user_households.validators import (
    AssociationHouseholdNotFoundError,
    UserHouseholdNotFoundError,
)
from tests.unit.v2.user_service_support import (
    ALICE,
    BOB,
    MAPPED_LEGACY_HOUSEHOLD_ID,
    default_legacy_references,
    v2_store,
)


@pytest.fixture
def store():
    with v2_store() as selected:
        service = V2UserHouseholdService(
            UserHouseholdDatabaseSession(selected.sessions),
            default_legacy_references(),
        )
        yield service, selected


def _fields(**changes) -> UserHouseholdCreateFields:
    values: dict[str, object] = {"country_id": "us", "legacy_household_id": 10}
    values.update(changes)
    return UserHouseholdCreateFields.model_validate(values)


def test_legacy_households_resolve_copied_v2_households(store) -> None:
    service, selected = store

    unmapped = service.create_user_household(
        principal=ALICE, association_input=_fields(name="Unmapped")
    )
    mapped = service.create_user_household(
        principal=ALICE,
        association_input=_fields(legacy_household_id=MAPPED_LEGACY_HOUSEHOLD_ID),
    )
    v2_only = service.create_user_household(
        principal=ALICE,
        association_input=UserHouseholdCreateFields(
            country_id="us", household_id=selected.household_id
        ),
    )

    assert (unmapped.household_id, unmapped.legacy_household_id) == (None, 10)
    assert mapped.household_id == selected.household_id
    assert v2_only.legacy_household_id is None
    assert unmapped.user_id == mapped.user_id == v2_only.user_id


def test_missing_references_are_rejected(store) -> None:
    service, selected = store

    with pytest.raises(LegacyReferenceNotFoundError):
        service.create_user_household(
            principal=ALICE, association_input=_fields(legacy_household_id=404)
        )
    with pytest.raises(AssociationHouseholdNotFoundError):
        service.create_user_household(
            principal=ALICE,
            association_input=UserHouseholdCreateFields(
                country_id="us", household_id=selected.policy_id
            ),
        )


def test_ownership_repointing_and_deletion(store) -> None:
    service, selected = store
    created = service.create_user_household(
        principal=ALICE, association_input=_fields(name="Family")
    )

    with pytest.raises(UserHouseholdNotFoundError):
        service.get_user_household(
            principal=BOB, country_id="us", association_id=created.id
        )
    with pytest.raises(UserHouseholdNotFoundError):
        service.delete_user_household(
            principal=BOB, country_id="us", association_id=created.id
        )
    assert service.list_user_households(principal=BOB, country_id="us").items == ()

    repointed = service.patch_user_household(
        principal=ALICE,
        country_id="us",
        association_id=created.id,
        association_input=UserHouseholdUpdateInput(
            legacy_household_id=MAPPED_LEGACY_HOUSEHOLD_ID
        ),
    )
    cleared = service.patch_user_household(
        principal=ALICE,
        country_id="us",
        association_id=created.id,
        association_input=UserHouseholdUpdateInput(legacy_household_id=11, name=None),
    )
    assert repointed.household_id == selected.household_id
    assert (cleared.household_id, cleared.legacy_household_id, cleared.name) == (
        None,
        11,
        None,
    )

    service.delete_user_household(
        principal=ALICE, country_id="us", association_id=created.id
    )
    with selected.sessions() as session:
        assert session.exec(select(UserHouseholdAssociation)).all() == []
        assert session.get(Household, selected.household_id) is not None


def test_patch_input_rejects_reassignment_and_empty_changes() -> None:
    with pytest.raises(ValueError):
        UserHouseholdUpdateInput()
    with pytest.raises(ValueError):
        UserHouseholdUpdateInput.model_validate(
            {"household_id": "00000000-0000-0000-0000-000000000001"}
        )
    with pytest.raises(ValueError):
        UserHouseholdUpdateInput(legacy_household_id=None)
