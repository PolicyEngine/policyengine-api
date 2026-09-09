"""Service tests for native v2 user-household associations."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session, create_engine, select

from policyengine_api.data.v2.models import (
    Household,
    User,
    UserHouseholdAssociation,
    V2_METADATA,
)
from policyengine_api.services.v2.user_households.database_session import (
    UserHouseholdDatabaseSession,
)
from policyengine_api.services.v2.user_households.services import (
    V2UserHouseholdService,
)
from policyengine_api.services.v2.user_households.types import (
    UserHouseholdCreationInput,
    UserHouseholdUpdateInput,
)
from policyengine_api.services.v2.user_households.validators import (
    AssociationCountryConflictError,
    AssociationHouseholdNotFoundError,
    AssociationUserNotFoundError,
    UserHouseholdNotFoundError,
)


USER_ID = UUID("00000000-0000-0000-0000-000000000070")
OTHER_USER_ID = UUID("00000000-0000-0000-0000-000000000071")


@pytest.fixture
def association_store():
    engine = create_engine("sqlite://")

    @sa.event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    V2_METADATA.create_all(engine)
    sessions = sessionmaker(engine, class_=Session, expire_on_commit=False)
    with sessions.begin() as session:
        first = Household(
            country_id="us",
            default_year=2026,
            household_data={"people": [], "household": []},
            canonicalization_version=1,
            content_hash="a" * 64,
        )
        replacement = Household(
            country_id="us",
            default_year=2027,
            household_data={"people": [], "household": []},
            canonicalization_version=1,
            content_hash="b" * 64,
        )
        uk = Household(
            country_id="uk",
            default_year=2026,
            household_data={"people": [], "household": [], "benunit": []},
            canonicalization_version=1,
            content_hash="c" * 64,
        )
        session.add_all(
            [
                first,
                replacement,
                uk,
                User(id=USER_ID, primary_country="us"),
                User(id=OTHER_USER_ID, primary_country="us"),
            ]
        )
        session.flush()
        identities = (first.id, replacement.id, uk.id)

    yield (
        V2UserHouseholdService(UserHouseholdDatabaseSession(sessions)),
        sessions,
        identities,
    )
    engine.dispose()


def _command(household_id, **changes) -> UserHouseholdCreationInput:
    values = {
        "country_id": "us",
        "user_id": USER_ID,
        "household_id": household_id,
        "name": "Saved household",
        "description": "Personal note",
    }
    values.update(changes)
    return UserHouseholdCreationInput.model_validate(values)


def test_create_allows_distinct_duplicate_links_for_an_existing_user(
    association_store,
) -> None:
    service, sessions, (household_id, _replacement_id, _uk_id) = association_store

    first = service.create_user_household(_command(household_id))
    second = service.create_user_household(_command(household_id, name="Second save"))

    assert first.id != second.id
    assert first.user_id == USER_ID
    assert second.household_id == household_id
    with sessions() as session:
        assert len(session.exec(select(UserHouseholdAssociation)).all()) == 2


def test_create_rejects_missing_dependencies_and_country_conflict(
    association_store,
) -> None:
    service, _sessions, (household_id, _replacement_id, _uk_id) = association_store

    with pytest.raises(AssociationHouseholdNotFoundError):
        service.create_user_household(_command(uuid4()))
    with pytest.raises(AssociationUserNotFoundError):
        service.create_user_household(_command(household_id, user_id=uuid4()))
    with pytest.raises(AssociationCountryConflictError):
        service.create_user_household(_command(household_id, country_id="uk"))


def test_detail_list_filter_and_pagination_are_country_scoped(
    association_store,
) -> None:
    service, _sessions, (household_id, replacement_id, _uk_id) = association_store
    first = service.create_user_household(_command(household_id, name="First"))
    service.create_user_household(_command(replacement_id, name="Second"))
    service.create_user_household(
        _command(household_id, user_id=OTHER_USER_ID, name="Other")
    )

    detail = service.get_user_household(country_id="us", association_id=first.id)
    filtered = service.list_user_households(
        country_id="us",
        user_id=USER_ID,
        household_id=household_id,
        limit=1,
    )
    second_page = service.list_user_households(
        country_id="us",
        user_id=USER_ID,
        offset=1,
        limit=1,
    )

    assert detail.id == first.id
    assert [item.name for item in filtered.items] == ["First"]
    assert filtered.has_more is False
    assert [item.name for item in second_page.items] == ["Second"]
    with pytest.raises(UserHouseholdNotFoundError):
        service.get_user_household(country_id="uk", association_id=first.id)


def test_patch_clears_presentation_data_and_reassigns_without_changing_identity(
    association_store,
) -> None:
    service, sessions, (household_id, replacement_id, _uk_id) = association_store
    created = service.create_user_household(_command(household_id))

    cleared = service.patch_user_household(
        country_id="us",
        association_id=created.id,
        association_input=UserHouseholdUpdateInput(name=None, description=None),
    )
    reassigned = service.patch_user_household(
        country_id="us",
        association_id=created.id,
        association_input=UserHouseholdUpdateInput(household_id=replacement_id),
    )

    assert cleared.name is None
    assert cleared.description is None
    assert reassigned.id == created.id
    assert reassigned.user_id == created.user_id
    assert reassigned.country_id == created.country_id
    assert reassigned.household_id == replacement_id
    with sessions() as session:
        assert session.get(Household, household_id) is not None
        assert session.get(Household, replacement_id) is not None


def test_failed_reassignment_leaves_association_unchanged(association_store) -> None:
    service, sessions, (household_id, _replacement_id, uk_id) = association_store
    created = service.create_user_household(_command(household_id))

    with pytest.raises(AssociationHouseholdNotFoundError):
        service.patch_user_household(
            country_id="us",
            association_id=created.id,
            association_input=UserHouseholdUpdateInput(household_id=uuid4()),
        )
    with pytest.raises(AssociationCountryConflictError):
        service.patch_user_household(
            country_id="us",
            association_id=created.id,
            association_input=UserHouseholdUpdateInput(household_id=uk_id),
        )

    with sessions() as session:
        stored = session.get(UserHouseholdAssociation, created.id)
        assert stored is not None
        assert stored.household_id == household_id


def test_delete_removes_only_association(association_store) -> None:
    service, sessions, (household_id, _replacement_id, _uk_id) = association_store
    created = service.create_user_household(_command(household_id))

    service.delete_user_household(country_id="us", association_id=created.id)

    with sessions() as session:
        assert session.get(UserHouseholdAssociation, created.id) is None
        assert session.get(Household, household_id) is not None
        assert session.get(User, USER_ID) is not None


def test_patch_rejects_empty_null_household_and_immutable_fields() -> None:
    with pytest.raises(ValueError):
        UserHouseholdUpdateInput()
    with pytest.raises(ValueError):
        UserHouseholdUpdateInput(household_id=None)
    with pytest.raises(ValueError):
        UserHouseholdUpdateInput.model_validate({"user_id": str(USER_ID)})
    with pytest.raises(ValueError):
        UserHouseholdUpdateInput.model_validate({"country_id": "us"})
