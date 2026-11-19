"""Service tests for users' saved dynamics (``user_dynamics``)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from policyengine_api.services.v2.user_dynamics.database_session import (
    UserDynamicDatabaseSession,
)
from policyengine_api.services.v2.user_dynamics.services import (
    V2UserDynamicService,
    create_user_dynamic_in_session,
)
from policyengine_api.services.v2.user_dynamics.types import (
    UserDynamicCreateFields,
    UserDynamicCreationInput,
    UserDynamicFilter,
    UserDynamicUpdateInput,
)
from policyengine_api.services.v2.user_dynamics.validators import (
    AssociationDynamicCountryConflictError,
    AssociationDynamicNotFoundError,
    UserDynamicNotFoundError,
)
from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from policyengine_api.data.v2.models import Dynamic, User, UserDynamic, UserType
from policyengine_api.services.v2.identity.types import AccountConversionOutcome
from policyengine_api.services.v2.user_accounts.database_session import (
    AccountDatabaseSession,
)
from policyengine_api.services.v2.user_accounts.services import V2AccountService
from tests.unit.v2.user_service_support import (
    ALICE,
    BOB,
    OTHER_SIGNED_OUT_BROWSER,
    SIGNED_OUT_BROWSER,
    V2Store,
    v2_store,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from uuid import UUID


@pytest.fixture
def store() -> Iterator[V2Store]:
    with v2_store() as selected:
        yield selected


@pytest.fixture
def saved_dynamics(store: V2Store) -> V2UserDynamicService:
    return V2UserDynamicService(UserDynamicDatabaseSession(store.sessions))


def _fields(dynamic_id: UUID, **changes: object) -> UserDynamicCreateFields:
    values: dict[str, object] = {
        "country_id": "us",
        "dynamic_id": dynamic_id,
        "name": "CBO labour supply responses",
        "description": "Income and substitution elasticities",
    }
    values.update(changes)
    return UserDynamicCreateFields.model_validate(values)


def _saved_dynamic_count(store: V2Store) -> int:
    with store.sessions() as session:
        return int(
            session.execute(select(func.count()).select_from(UserDynamic)).scalar_one()
        )


def test_first_save_provisions_the_owner_and_stores_the_name(
    store: V2Store, saved_dynamics: V2UserDynamicService
) -> None:
    created = saved_dynamics.create_user_dynamic(
        principal=ALICE, association_input=_fields(store.dynamic_id)
    )

    assert created.country_id == "us"
    assert created.dynamic_id == store.dynamic_id
    assert created.name == "CBO labour supply responses"
    assert created.description == "Income and substitution elasticities"
    with store.sessions() as session:
        owner = session.get(User, created.user_id)
        stored = session.get(UserDynamic, created.id)
    assert owner is not None
    assert owner.user_type == UserType.STANDARD.value
    assert stored is not None
    assert stored.user_id == created.user_id
    assert (
        saved_dynamics.get_user_dynamic(
            principal=ALICE, country_id="us", association_id=created.id
        )
        == created
    )


def test_a_signed_out_browser_saves_and_reads_only_its_own_dynamics(
    store: V2Store, saved_dynamics: V2UserDynamicService
) -> None:
    before = saved_dynamics.list_user_dynamics(
        principal=SIGNED_OUT_BROWSER, country_id="us"
    )
    with store.sessions() as session:
        assert session.get(User, SIGNED_OUT_BROWSER.user_id) is None

    created = saved_dynamics.create_user_dynamic(
        principal=SIGNED_OUT_BROWSER, association_input=_fields(store.dynamic_id)
    )
    listed = saved_dynamics.list_user_dynamics(
        principal=SIGNED_OUT_BROWSER, country_id="us"
    )

    assert before.items == ()
    assert created.user_id == SIGNED_OUT_BROWSER.user_id
    assert [item.id for item in listed.items] == [created.id]
    with store.sessions() as session:
        browser_user = session.get(User, SIGNED_OUT_BROWSER.user_id)
    assert browser_user is not None
    assert browser_user.user_type == UserType.UNAUTHENTICATED.value
    assert (
        saved_dynamics.list_user_dynamics(
            principal=OTHER_SIGNED_OUT_BROWSER, country_id="us"
        ).items
        == ()
    )
    with pytest.raises(UserDynamicNotFoundError):
        saved_dynamics.get_user_dynamic(
            principal=OTHER_SIGNED_OUT_BROWSER,
            country_id="us",
            association_id=created.id,
        )


def test_another_users_saved_dynamic_cannot_be_read_changed_or_deleted(
    store: V2Store, saved_dynamics: V2UserDynamicService
) -> None:
    created = saved_dynamics.create_user_dynamic(
        principal=ALICE, association_input=_fields(store.dynamic_id)
    )
    saved_dynamics.create_user_dynamic(
        principal=BOB, association_input=_fields(store.dynamic_id, name="Bob's")
    )

    with pytest.raises(UserDynamicNotFoundError):
        saved_dynamics.get_user_dynamic(
            principal=BOB, country_id="us", association_id=created.id
        )
    with pytest.raises(UserDynamicNotFoundError):
        saved_dynamics.patch_user_dynamic(
            principal=BOB,
            country_id="us",
            association_id=created.id,
            association_input=UserDynamicUpdateInput(name="Taken over"),
        )
    with pytest.raises(UserDynamicNotFoundError):
        saved_dynamics.delete_user_dynamic(
            principal=BOB, country_id="us", association_id=created.id
        )
    with pytest.raises(UserDynamicNotFoundError):
        saved_dynamics.get_user_dynamic(
            principal=ALICE, country_id="uk", association_id=created.id
        )

    bobs_names = [
        item.name
        for item in saved_dynamics.list_user_dynamics(
            principal=BOB, country_id="us"
        ).items
    ]
    assert bobs_names == ["Bob's"]
    assert (
        saved_dynamics.get_user_dynamic(
            principal=ALICE, country_id="us", association_id=created.id
        )
        == created
    )


def test_a_saved_dynamic_names_a_dynamic_stored_in_its_own_country(
    store: V2Store, saved_dynamics: V2UserDynamicService
) -> None:
    with pytest.raises(AssociationDynamicCountryConflictError):
        saved_dynamics.create_user_dynamic(
            principal=ALICE, association_input=_fields(store.uk_dynamic_id)
        )
    with pytest.raises(AssociationDynamicNotFoundError):
        saved_dynamics.create_user_dynamic(
            principal=ALICE, association_input=_fields(uuid4())
        )

    assert _saved_dynamic_count(store) == 0
    uk_saved = saved_dynamics.create_user_dynamic(
        principal=ALICE,
        association_input=_fields(store.uk_dynamic_id, country_id="uk"),
    )
    assert uk_saved.country_id == "uk"


def test_patch_renames_and_repoints_within_the_country(
    store: V2Store, saved_dynamics: V2UserDynamicService
) -> None:
    created = saved_dynamics.create_user_dynamic(
        principal=ALICE, association_input=_fields(store.dynamic_id)
    )

    renamed = saved_dynamics.patch_user_dynamic(
        principal=ALICE,
        country_id="us",
        association_id=created.id,
        association_input=UserDynamicUpdateInput(name="Renamed", description=None),
    )
    repointed = saved_dynamics.patch_user_dynamic(
        principal=ALICE,
        country_id="us",
        association_id=created.id,
        association_input=UserDynamicUpdateInput(dynamic_id=store.other_dynamic_id),
    )
    with pytest.raises(AssociationDynamicCountryConflictError):
        saved_dynamics.patch_user_dynamic(
            principal=ALICE,
            country_id="us",
            association_id=created.id,
            association_input=UserDynamicUpdateInput(dynamic_id=store.uk_dynamic_id),
        )
    with pytest.raises(AssociationDynamicNotFoundError):
        saved_dynamics.patch_user_dynamic(
            principal=ALICE,
            country_id="us",
            association_id=created.id,
            association_input=UserDynamicUpdateInput(dynamic_id=uuid4()),
        )

    assert (renamed.name, renamed.description, renamed.dynamic_id) == (
        "Renamed",
        None,
        store.dynamic_id,
    )
    assert renamed.updated_at > created.updated_at
    assert (repointed.name, repointed.dynamic_id) == (
        "Renamed",
        store.other_dynamic_id,
    )
    assert (repointed.id, repointed.user_id, repointed.created_at) == (
        created.id,
        created.user_id,
        created.created_at,
    )
    assert (
        saved_dynamics.get_user_dynamic(
            principal=ALICE, country_id="us", association_id=created.id
        )
        == repointed
    )


@pytest.mark.parametrize(
    "update",
    [{}, {"dynamic_id": None}, {"user_id": str(uuid4())}, {"name": "x" * 256}],
)
def test_an_update_names_a_change_and_never_clears_the_dynamic(
    update: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        UserDynamicUpdateInput.model_validate(update)


@pytest.mark.parametrize(
    "fields",
    [
        {"country_id": "us"},
        {"country_id": "us", "dynamic_id": None},
        {"country_id": "fr", "dynamic_id": str(uuid4())},
        {"country_id": "us", "dynamic_id": str(uuid4()), "user_id": str(uuid4())},
        {"country_id": "us", "dynamic_id": str(uuid4()), "legacy_policy_id": 1},
    ],
)
def test_a_save_names_one_dynamic_and_no_owner_or_v1_reference(
    fields: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        UserDynamicCreateFields.model_validate(fields)


def test_delete_removes_only_the_saved_dynamic(
    store: V2Store, saved_dynamics: V2UserDynamicService
) -> None:
    created = saved_dynamics.create_user_dynamic(
        principal=ALICE, association_input=_fields(store.dynamic_id)
    )

    saved_dynamics.delete_user_dynamic(
        principal=ALICE, country_id="us", association_id=created.id
    )

    with pytest.raises(UserDynamicNotFoundError):
        saved_dynamics.get_user_dynamic(
            principal=ALICE, country_id="us", association_id=created.id
        )
    with pytest.raises(UserDynamicNotFoundError):
        saved_dynamics.delete_user_dynamic(
            principal=ALICE, country_id="us", association_id=created.id
        )
    with store.sessions() as session:
        assert session.get(Dynamic, store.dynamic_id) is not None


def test_list_pages_in_creation_order_and_filters_by_dynamic(
    store: V2Store, saved_dynamics: V2UserDynamicService
) -> None:
    created = [
        saved_dynamics.create_user_dynamic(
            principal=ALICE,
            association_input=_fields(dynamic_id, name=f"Saved {position}"),
        )
        for position, dynamic_id in enumerate(
            (store.dynamic_id, store.other_dynamic_id, store.dynamic_id)
        )
    ]

    first_page = saved_dynamics.list_user_dynamics(
        principal=ALICE, country_id="us", offset=0, limit=2
    )
    second_page = saved_dynamics.list_user_dynamics(
        principal=ALICE, country_id="us", offset=2, limit=2
    )
    filtered = saved_dynamics.list_user_dynamics(
        principal=ALICE,
        country_id="us",
        dynamic_filter=UserDynamicFilter(dynamic_id=store.dynamic_id),
    )

    assert [item.id for item in first_page.items] == [created[0].id, created[1].id]
    assert first_page.has_more is True
    assert [item.id for item in second_page.items] == [created[2].id]
    assert second_page.has_more is False
    assert [item.id for item in filtered.items] == [created[0].id, created[2].id]
    assert (
        saved_dynamics.list_user_dynamics(principal=ALICE, country_id="uk").items == ()
    )


def test_a_dynamic_that_a_user_saved_cannot_be_deleted(
    store: V2Store, saved_dynamics: V2UserDynamicService
) -> None:
    saved_dynamics.create_user_dynamic(
        principal=ALICE, association_input=_fields(store.dynamic_id)
    )

    with pytest.raises(IntegrityError), store.sessions.begin() as session:
        session.execute(delete(Dynamic).where(Dynamic.id == store.dynamic_id))


def test_deleting_a_user_deletes_their_saved_dynamics(
    store: V2Store, saved_dynamics: V2UserDynamicService
) -> None:
    alices = saved_dynamics.create_user_dynamic(
        principal=ALICE, association_input=_fields(store.dynamic_id)
    )
    bobs = saved_dynamics.create_user_dynamic(
        principal=BOB, association_input=_fields(store.dynamic_id)
    )

    with store.sessions.begin() as session:
        session.execute(delete(User).where(User.id == alices.user_id))

    with store.sessions() as session:
        assert session.get(UserDynamic, alices.id) is None
        assert session.get(UserDynamic, bobs.id) is not None
        assert session.get(Dynamic, store.dynamic_id) is not None


def test_signing_in_moves_a_browsers_saved_dynamics_to_the_account(
    store: V2Store, saved_dynamics: V2UserDynamicService
) -> None:
    accounts = V2AccountService(AccountDatabaseSession(store.sessions))
    alice_id = accounts.get_account(principal=ALICE, country_id="us").id
    alices = saved_dynamics.create_user_dynamic(
        principal=ALICE, association_input=_fields(store.dynamic_id)
    )
    browsers = saved_dynamics.create_user_dynamic(
        principal=SIGNED_OUT_BROWSER,
        association_input=_fields(store.other_dynamic_id, name="Browser's"),
    )

    upgrade = accounts.upgrade_account(
        principal=ALICE,
        unauthenticated_user_id=SIGNED_OUT_BROWSER.user_id,
        country_id="us",
    )

    assert upgrade.outcome is AccountConversionOutcome.MERGED
    moved = saved_dynamics.get_user_dynamic(
        principal=ALICE, country_id="us", association_id=browsers.id
    )
    assert (moved.user_id, moved.name, moved.created_at, moved.updated_at) == (
        alice_id,
        "Browser's",
        browsers.created_at,
        browsers.updated_at,
    )
    assert [
        item.id
        for item in saved_dynamics.list_user_dynamics(
            principal=ALICE, country_id="us"
        ).items
    ] == [alices.id, browsers.id]


def test_the_account_export_lists_saved_dynamics_in_every_country(
    store: V2Store, saved_dynamics: V2UserDynamicService
) -> None:
    accounts = V2AccountService(AccountDatabaseSession(store.sessions))
    us_saved = saved_dynamics.create_user_dynamic(
        principal=ALICE, association_input=_fields(store.dynamic_id)
    )
    uk_saved = saved_dynamics.create_user_dynamic(
        principal=ALICE,
        association_input=_fields(store.uk_dynamic_id, country_id="uk"),
    )
    saved_dynamics.create_user_dynamic(
        principal=BOB, association_input=_fields(store.dynamic_id)
    )

    exported = accounts.export_account(principal=ALICE, country_id="us")
    browser_export = accounts.export_account(
        principal=SIGNED_OUT_BROWSER, country_id="us"
    )

    assert exported.dynamics == (us_saved, uk_saved)
    assert browser_export.user is None
    assert browser_export.dynamics == ()


def test_the_migration_saves_a_dynamic_for_a_user_it_names(
    store: V2Store, saved_dynamics: V2UserDynamicService
) -> None:
    owner_id = (
        V2AccountService(AccountDatabaseSession(store.sessions))
        .get_account(principal=ALICE, country_id="us")
        .id
    )
    creation_input = UserDynamicCreationInput(
        country_id="us",
        user_id=owner_id,
        dynamic_id=store.dynamic_id,
        name="Saved reform's assumptions",
        description=None,
    )

    with store.sessions.begin() as session:
        created = create_user_dynamic_in_session(session, creation_input)
    with (
        pytest.raises(AssociationDynamicCountryConflictError),
        store.sessions.begin() as session,
    ):
        create_user_dynamic_in_session(
            session,
            creation_input.model_copy(update={"dynamic_id": store.uk_dynamic_id}),
        )

    assert created.user_id == owner_id
    assert created.name == "Saved reform's assumptions"
    assert (
        saved_dynamics.get_user_dynamic(
            principal=ALICE, country_id="us", association_id=created.id
        )
        == created
    )
    assert _saved_dynamic_count(store) == 1
