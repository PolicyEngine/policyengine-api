"""Service tests for v2 user-household associations."""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlmodel import select

from policyengine_api.data.v2.models import Household, UserHouseholdAssociation
from policyengine_api.services.v2.associations.validators import (
    AssociationReferenceConflictError,
)
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
    AssociationCountryConflictError,
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
    with pytest.raises(UserHouseholdNotFoundError):
        service.patch_user_household(
            principal=BOB,
            country_id="us",
            association_id=created.id,
            association_input=UserHouseholdUpdateInput(
                household_id=selected.household_id
            ),
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


def test_repointing_to_a_v2_household_keeps_the_saved_row_and_clears_the_v1_reference(
    store,
) -> None:
    service, selected = store
    created = service.create_user_household(
        principal=ALICE, association_input=_fields(name="Family", description="Note")
    )

    repointed = service.patch_user_household(
        principal=ALICE,
        country_id="us",
        association_id=created.id,
        association_input=UserHouseholdUpdateInput(household_id=selected.household_id),
    )

    assert (repointed.household_id, repointed.legacy_household_id) == (
        selected.household_id,
        None,
    )
    assert (repointed.id, repointed.name, repointed.description) == (
        created.id,
        "Family",
        "Note",
    )
    assert repointed.created_at == created.created_at
    assert repointed.updated_at >= created.updated_at
    with selected.sessions() as session:
        stored = session.get(UserHouseholdAssociation, created.id)
        assert stored is not None
        assert (stored.household_id, stored.legacy_household_id) == (
            selected.household_id,
            None,
        )


def test_repointing_to_both_household_references_stores_both(store) -> None:
    service, selected = store
    created = service.create_user_household(
        principal=ALICE, association_input=_fields()
    )

    copied = service.patch_user_household(
        principal=ALICE,
        country_id="us",
        association_id=created.id,
        association_input=UserHouseholdUpdateInput(
            household_id=selected.household_id,
            legacy_household_id=MAPPED_LEGACY_HOUSEHOLD_ID,
        ),
    )
    assert (copied.household_id, copied.legacy_household_id) == (
        selected.household_id,
        MAPPED_LEGACY_HOUSEHOLD_ID,
    )

    # v1 household 11 has no v2 copy, so nothing can contradict the v2
    # reference: both are stored, as creation stores them.
    uncopied = service.patch_user_household(
        principal=ALICE,
        country_id="us",
        association_id=created.id,
        association_input=UserHouseholdUpdateInput(
            household_id=selected.household_id, legacy_household_id=11
        ),
    )
    assert (uncopied.household_id, uncopied.legacy_household_id) == (
        selected.household_id,
        11,
    )
    assert uncopied.id == created.id


def test_repointing_to_a_missing_foreign_or_conflicting_household_changes_nothing(
    store,
) -> None:
    service, selected = store
    created = service.create_user_household(
        principal=ALICE, association_input=_fields(name="Family")
    )
    with selected.sessions.begin() as session:
        other_us_household = Household(
            country_id="us",
            default_year=2026,
            household_data={"people": [], "household": []},
            canonicalization_version=1,
            content_hash="e" * 64,
        )
        session.add(other_us_household)
        session.flush()
        other_us_household_id = other_us_household.id

    rejected_updates = (
        (
            AssociationHouseholdNotFoundError,
            UserHouseholdUpdateInput(
                household_id=UUID("00000000-0000-0000-0000-000000000099"),
                name="Lost",
            ),
        ),
        (
            AssociationCountryConflictError,
            UserHouseholdUpdateInput(
                household_id=selected.uk_household_id, name="Lost"
            ),
        ),
        (
            AssociationReferenceConflictError,
            UserHouseholdUpdateInput(
                household_id=other_us_household_id,
                legacy_household_id=MAPPED_LEGACY_HOUSEHOLD_ID,
                name="Lost",
            ),
        ),
        (
            LegacyReferenceNotFoundError,
            UserHouseholdUpdateInput(
                household_id=selected.household_id,
                legacy_household_id=404,
                name="Lost",
            ),
        ),
    )
    for expected_error, rejected_update in rejected_updates:
        with pytest.raises(expected_error):
            service.patch_user_household(
                principal=ALICE,
                country_id="us",
                association_id=created.id,
                association_input=rejected_update,
            )

    unchanged = service.get_user_household(
        principal=ALICE, country_id="us", association_id=created.id
    )
    assert (
        unchanged.household_id,
        unchanged.legacy_household_id,
        unchanged.name,
    ) == (None, 10, "Family")
    assert unchanged.updated_at == created.updated_at


def test_patch_input_rejects_reassignment_and_empty_changes() -> None:
    with pytest.raises(
        ValueError, match="At least one of household_id, legacy_household_id"
    ):
        UserHouseholdUpdateInput()
    with pytest.raises(ValueError, match=r"user_id\n  Extra inputs are not permitted"):
        UserHouseholdUpdateInput.model_validate(
            {"user_id": "00000000-0000-0000-0000-0000000000a1"}
        )
    with pytest.raises(ValueError, match="legacy_household_id must not be null"):
        UserHouseholdUpdateInput(legacy_household_id=None)
    with pytest.raises(ValueError, match="household_id must not be null"):
        UserHouseholdUpdateInput(household_id=None)


def test_patch_input_accepts_a_v2_household_reference() -> None:
    repoint = UserHouseholdUpdateInput.model_validate(
        {"household_id": "00000000-0000-0000-0000-000000000001"}
    )

    assert repoint.household_id == UUID("00000000-0000-0000-0000-000000000001")
    assert repoint.model_fields_set == {"household_id"}
