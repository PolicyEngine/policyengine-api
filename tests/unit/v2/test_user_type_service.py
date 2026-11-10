"""Service tests for minimum user types and admins' changes to users' types."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from sqlmodel import select

from policyengine_api.data.v2.models import (
    User,
    UserIdentity,
    UserType,
    UserTypeChange,
    UserTypeChangeSource,
)
from policyengine_api.services.v2.identity.types import UserPrincipal
from policyengine_api.services.v2.user_accounts.database_session import (
    AccountDatabaseSession,
)
from policyengine_api.services.v2.user_accounts.services import V2AccountService
from policyengine_api.services.v2.user_policies.database_session import (
    UserPolicyDatabaseSession,
)
from policyengine_api.services.v2.user_policies.services import V2UserPolicyService
from policyengine_api.services.v2.user_policies.types import UserPolicyCreateFields
from policyengine_api.services.v2.user_types.database_session import (
    UserTypeDatabaseSession,
)
from policyengine_api.services.v2.user_types.services import V2UserTypeService
from policyengine_api.services.v2.user_types.types import AdminUserSearch
from policyengine_api.services.v2.user_types.validators import (
    LastAdminDeletionError,
    LastAdminDemotionError,
    SignedInUserNotFoundError,
    UserEmailMatchError,
    UserTypeBelowMinimumError,
    UserTypeChangedError,
)
from tests.unit.v2.user_service_support import (
    ALICE,
    BOB,
    ISSUER,
    SIGNED_OUT_BROWSER,
    V2Store,
    default_legacy_references,
    v2_store,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from uuid import UUID

CAROL = UserPrincipal(
    issuer=ISSUER, subject="google-oauth2|carol", email="carol@example.test"
)
ALICE_WITH_EMAIL = UserPrincipal(
    issuer=ALICE.issuer, subject=ALICE.subject, email="alice@example.test"
)
BOB_WITH_EMAIL = UserPrincipal(
    issuer=BOB.issuer, subject=BOB.subject, email="bob@example.test"
)


def _never_build_the_auth0_deleter():
    msg = "these tests delete no account"
    raise AssertionError(msg)


@pytest.fixture
def store() -> Iterator[V2Store]:
    with v2_store() as isolated_store:
        yield isolated_store


def _user_types(store: V2Store) -> V2UserTypeService:
    return V2UserTypeService(UserTypeDatabaseSession(store.sessions))


def _sign_in(store: V2Store, principal: UserPrincipal, country_id: str = "us") -> UUID:
    accounts = V2AccountService(
        AccountDatabaseSession(store.sessions),
        auth0_user_deleter_factory=_never_build_the_auth0_deleter,
    )
    return accounts.get_account(principal=principal, country_id=country_id).id


def _store_type(store: V2Store, user_id: UUID, user_type: UserType) -> None:
    with store.sessions.begin() as session:
        user = session.get(User, user_id)
        assert user is not None
        user.user_type = user_type.value


def _stored_type(store: V2Store, user_id: UUID) -> str:
    with store.sessions() as session:
        user = session.get(User, user_id)
        assert user is not None
        return user.user_type


def _signed_in_admin(store: V2Store, principal: UserPrincipal) -> UUID:
    user_id = _sign_in(store, principal)
    _store_type(store, user_id, UserType.ADMIN)
    return user_id


def _history_rows(store: V2Store) -> list[UserTypeChange]:
    with store.sessions() as session:
        return list(session.exec(select(UserTypeChange)).all())


@pytest.mark.parametrize(
    ("stored_type", "minimum"),
    [
        (UserType.STANDARD, UserType.STANDARD),
        (UserType.AUTHOR, UserType.STANDARD),
        (UserType.AUTHOR, UserType.AUTHOR),
        (UserType.ADMIN, UserType.AUTHOR),
        (UserType.ADMIN, UserType.ADMIN),
    ],
)
def test_a_signed_in_user_at_or_above_the_minimum_passes(
    store: V2Store, stored_type: UserType, minimum: UserType
) -> None:
    user_id = _sign_in(store, ALICE)
    _store_type(store, user_id, stored_type)

    caller_type = _user_types(store).require_minimum_user_type(
        principal=ALICE, minimum=minimum
    )

    assert caller_type is stored_type


@pytest.mark.parametrize(
    ("stored_type", "minimum"),
    [
        (UserType.STANDARD, UserType.AUTHOR),
        (UserType.STANDARD, UserType.ADMIN),
        (UserType.AUTHOR, UserType.ADMIN),
    ],
)
def test_a_signed_in_user_below_the_minimum_is_refused(
    store: V2Store, stored_type: UserType, minimum: UserType
) -> None:
    user_id = _sign_in(store, ALICE)
    _store_type(store, user_id, stored_type)

    with pytest.raises(UserTypeBelowMinimumError):
        _user_types(store).require_minimum_user_type(principal=ALICE, minimum=minimum)


def test_callers_without_a_signed_in_user_are_below_every_signed_in_type(
    store: V2Store,
) -> None:
    user_types = _user_types(store)
    V2UserPolicyService(
        UserPolicyDatabaseSession(store.sessions), default_legacy_references()
    ).create_user_policy(
        principal=SIGNED_OUT_BROWSER,
        association_input=UserPolicyCreateFields(country_id="us", legacy_policy_id=1),
    )

    for principal in (SIGNED_OUT_BROWSER, BOB):
        with pytest.raises(UserTypeBelowMinimumError):
            user_types.require_minimum_user_type(
                principal=principal, minimum=UserType.AUTHOR
            )
    # Bob has no user yet, but his first request will provision a standard one.
    assert (
        user_types.require_minimum_user_type(principal=BOB, minimum=UserType.STANDARD)
        is UserType.STANDARD
    )
    with pytest.raises(UserTypeBelowMinimumError):
        user_types.require_minimum_user_type(
            principal=SIGNED_OUT_BROWSER, minimum=UserType.STANDARD
        )
    # The check reads only: Bob, never seen before, is not provisioned.
    with store.sessions() as session:
        assert session.exec(select(UserIdentity)).all() == []


def test_admins_find_signed_in_users_by_part_of_an_email(store: V2Store) -> None:
    _signed_in_admin(store, ALICE_WITH_EMAIL)
    bob_id = _sign_in(store, BOB_WITH_EMAIL)
    carol_id = _sign_in(store, CAROL, country_id="uk")
    V2UserPolicyService(
        UserPolicyDatabaseSession(store.sessions), default_legacy_references()
    ).create_user_policy(
        principal=SIGNED_OUT_BROWSER,
        association_input=UserPolicyCreateFields(country_id="us", legacy_policy_id=1),
    )
    user_types = _user_types(store)

    matching = user_types.list_users(
        principal=ALICE_WITH_EMAIL, search=AdminUserSearch(email="CAROL@example")
    )
    everyone = user_types.list_users(
        principal=ALICE_WITH_EMAIL, search=AdminUserSearch(limit=2)
    )
    wildcard = user_types.list_users(
        principal=ALICE_WITH_EMAIL, search=AdminUserSearch(email="%")
    )

    assert [(user.id, user.email, user.user_type) for user in matching.items] == [
        (carol_id, "carol@example.test", UserType.STANDARD)
    ]
    assert matching.items[0].primary_country == "uk"
    assert matching.has_more is False
    # Unauthenticated users are never listed: their IDs are credentials.
    assert len(everyone.items) == 2
    assert everyone.has_more is True
    assert bob_id in {
        user.id
        for user in user_types.list_users(
            principal=ALICE_WITH_EMAIL, search=AdminUserSearch(offset=0, limit=10)
        ).items
    }
    assert SIGNED_OUT_BROWSER.user_id not in {
        user.id
        for user in user_types.list_users(
            principal=ALICE_WITH_EMAIL, search=AdminUserSearch(limit=10)
        ).items
    }
    # A LIKE wildcard in the search is matched literally.
    assert wildcard.items == ()


def test_only_admins_list_read_or_change_users(store: V2Store) -> None:
    _sign_in(store, ALICE)
    bob_id = _sign_in(store, BOB)
    _store_type(store, bob_id, UserType.AUTHOR)
    user_types = _user_types(store)

    for principal in (ALICE, BOB, SIGNED_OUT_BROWSER):
        with pytest.raises(UserTypeBelowMinimumError):
            user_types.list_users(principal=principal, search=AdminUserSearch())
        with pytest.raises(UserTypeBelowMinimumError):
            user_types.get_user(principal=principal, user_id=bob_id)
        with pytest.raises(UserTypeBelowMinimumError):
            user_types.change_user_type(
                principal=principal,
                user_id=bob_id,
                user_type=UserType.ADMIN,
                expected_user_type=UserType.AUTHOR,
            )
        with pytest.raises(UserTypeBelowMinimumError):
            user_types.list_user_type_changes(principal=principal, user_id=bob_id)
    assert _stored_type(store, bob_id) == "author"
    assert _history_rows(store) == []


def test_an_admin_changes_a_type_and_the_change_is_recorded(store: V2Store) -> None:
    alice_id = _signed_in_admin(store, ALICE_WITH_EMAIL)
    bob_id = _sign_in(store, BOB_WITH_EMAIL)
    user_types = _user_types(store)

    promoted = user_types.change_user_type(
        principal=ALICE_WITH_EMAIL,
        user_id=bob_id,
        user_type=UserType.AUTHOR,
        expected_user_type=UserType.STANDARD,
    )
    unchanged = user_types.change_user_type(
        principal=ALICE_WITH_EMAIL,
        user_id=bob_id,
        user_type=UserType.AUTHOR,
        expected_user_type=UserType.AUTHOR,
    )
    user_types.change_user_type(
        principal=ALICE_WITH_EMAIL,
        user_id=bob_id,
        user_type=UserType.ADMIN,
        expected_user_type=UserType.AUTHOR,
    )
    history = user_types.list_user_type_changes(
        principal=ALICE_WITH_EMAIL, user_id=bob_id
    )

    assert (promoted.id, promoted.user_type, promoted.email) == (
        bob_id,
        UserType.AUTHOR,
        "bob@example.test",
    )
    assert unchanged.user_type is UserType.AUTHOR
    assert _stored_type(store, bob_id) == "admin"
    # Newest first; setting the type a user already has records nothing.
    assert [
        (change.previous_user_type, change.new_user_type) for change in history
    ] == [
        (UserType.AUTHOR, UserType.ADMIN),
        (UserType.STANDARD, UserType.AUTHOR),
    ]
    assert {change.user_id for change in history} == {bob_id}
    assert {change.changed_by_user_id for change in history} == {alice_id}
    assert {change.changed_by_email for change in history} == {"alice@example.test"}
    assert {change.source for change in history} == {UserTypeChangeSource.ADMIN_ROUTE}


def test_admins_read_one_user_and_only_signed_in_users(store: V2Store) -> None:
    _signed_in_admin(store, ALICE)
    bob_id = _sign_in(store, BOB_WITH_EMAIL)
    V2UserPolicyService(
        UserPolicyDatabaseSession(store.sessions), default_legacy_references()
    ).create_user_policy(
        principal=SIGNED_OUT_BROWSER,
        association_input=UserPolicyCreateFields(country_id="us", legacy_policy_id=1),
    )
    user_types = _user_types(store)

    bob = user_types.get_user(principal=ALICE, user_id=bob_id)

    assert (bob.id, bob.email, bob.user_type) == (
        bob_id,
        "bob@example.test",
        UserType.STANDARD,
    )
    for operation in (
        lambda: user_types.get_user(
            principal=ALICE, user_id=SIGNED_OUT_BROWSER.user_id
        ),
        lambda: user_types.change_user_type(
            principal=ALICE,
            user_id=SIGNED_OUT_BROWSER.user_id,
            user_type=UserType.STANDARD,
            expected_user_type=UserType.STANDARD,
        ),
        lambda: user_types.list_user_type_changes(
            principal=ALICE, user_id=SIGNED_OUT_BROWSER.user_id
        ),
    ):
        with pytest.raises(SignedInUserNotFoundError):
            operation()
    with store.sessions() as session:
        browser_user = session.get(User, SIGNED_OUT_BROWSER.user_id)
        assert browser_user is not None
        assert browser_user.user_type == "unauthenticated"


def test_the_last_admin_is_never_demoted(store: V2Store) -> None:
    alice_id = _signed_in_admin(store, ALICE)
    user_types = _user_types(store)

    for user_type in (UserType.AUTHOR, UserType.STANDARD):
        with pytest.raises(LastAdminDemotionError):
            user_types.change_user_type(
                principal=ALICE,
                user_id=alice_id,
                user_type=user_type,
                expected_user_type=UserType.ADMIN,
            )
    assert _stored_type(store, alice_id) == "admin"

    bob_id = _sign_in(store, BOB)
    user_types.change_user_type(
        principal=ALICE,
        user_id=bob_id,
        user_type=UserType.ADMIN,
        expected_user_type=UserType.STANDARD,
    )
    demoted = user_types.change_user_type(
        principal=ALICE,
        user_id=alice_id,
        user_type=UserType.AUTHOR,
        expected_user_type=UserType.ADMIN,
    )

    assert demoted.user_type is UserType.AUTHOR
    # Alice is no longer an admin, so she can't change anyone's type.
    with pytest.raises(UserTypeBelowMinimumError):
        user_types.change_user_type(
            principal=ALICE,
            user_id=bob_id,
            user_type=UserType.STANDARD,
            expected_user_type=UserType.ADMIN,
        )
    with pytest.raises(LastAdminDemotionError):
        user_types.change_user_type(
            principal=BOB,
            user_id=bob_id,
            user_type=UserType.STANDARD,
            expected_user_type=UserType.ADMIN,
        )


def test_a_script_sets_a_type_by_email_and_records_it(store: V2Store) -> None:
    alice_id = _sign_in(store, ALICE_WITH_EMAIL)
    user_types = _user_types(store)

    first = user_types.set_user_type_by_email(
        email="Alice@Example.test", user_type=UserType.ADMIN
    )
    again = user_types.set_user_type_by_email(
        email="alice@example.test", user_type=UserType.ADMIN
    )

    assert (first.user.id, first.user.user_type, first.previous_user_type) == (
        alice_id,
        UserType.ADMIN,
        UserType.STANDARD,
    )
    assert (again.user.user_type, again.previous_user_type) == (
        UserType.ADMIN,
        UserType.ADMIN,
    )
    (change,) = _history_rows(store)
    assert (change.user_id, change.changed_by_user_id, change.source) == (
        alice_id,
        None,
        UserTypeChangeSource.SCRIPT.value,
    )
    with pytest.raises(LastAdminDemotionError):
        user_types.set_user_type_by_email(
            email="alice@example.test", user_type=UserType.STANDARD
        )


def test_a_script_needs_exactly_one_signed_in_user_with_the_email(
    store: V2Store,
) -> None:
    _sign_in(store, ALICE_WITH_EMAIL)
    _sign_in(
        store,
        UserPrincipal(
            issuer=ISSUER, subject="github|alice", email="alice@example.test"
        ),
    )
    user_types = _user_types(store)

    with pytest.raises(UserEmailMatchError, match="2 signed-in users"):
        user_types.set_user_type_by_email(
            email="alice@example.test", user_type=UserType.ADMIN
        )
    with pytest.raises(UserEmailMatchError, match="no signed-in user"):
        user_types.set_user_type_by_email(
            email="nobody@example.test", user_type=UserType.ADMIN
        )
    # A part of an email never matches: the script needs the whole address.
    with pytest.raises(UserEmailMatchError, match="no signed-in user"):
        user_types.set_user_type_by_email(email="alice", user_type=UserType.ADMIN)
    assert _history_rows(store) == []


def test_the_last_admin_cannot_delete_their_own_account(store: V2Store) -> None:
    alice_id = _signed_in_admin(store, ALICE)
    accounts = V2AccountService(AccountDatabaseSession(store.sessions))

    with pytest.raises(LastAdminDeletionError):
        accounts.delete_account(principal=ALICE)
    assert _stored_type(store, alice_id) == "admin"

    bob_id = _signed_in_admin(store, BOB)
    accounts.delete_account(principal=ALICE)

    with store.sessions() as session:
        assert session.get(User, alice_id) is None
    # Bob is now the last admin.
    with pytest.raises(LastAdminDeletionError):
        accounts.delete_account(principal=BOB)
    assert _stored_type(store, bob_id) == "admin"


def test_a_change_is_refused_once_the_type_differs_from_the_expected_one(
    store: V2Store,
) -> None:
    """Carol read Bob as standard, but Alice made him an author since."""
    alice_id = _signed_in_admin(store, ALICE)
    _signed_in_admin(store, CAROL)
    bob_id = _sign_in(store, BOB)
    user_types = _user_types(store)
    user_types.change_user_type(
        principal=ALICE,
        user_id=bob_id,
        user_type=UserType.AUTHOR,
        expected_user_type=UserType.STANDARD,
    )

    with pytest.raises(
        UserTypeChangedError,
        match=re.escape(
            "This user's type is now author, not standard. Nothing was changed."
        ),
    ):
        user_types.change_user_type(
            principal=CAROL,
            user_id=bob_id,
            user_type=UserType.ADMIN,
            expected_user_type=UserType.STANDARD,
        )
    # Asking for the type the user already has changes nothing, whatever was
    # expected.
    unchanged = user_types.change_user_type(
        principal=CAROL,
        user_id=bob_id,
        user_type=UserType.AUTHOR,
        expected_user_type=UserType.STANDARD,
    )

    assert unchanged.user_type is UserType.AUTHOR
    assert _stored_type(store, bob_id) == "author"
    assert [
        (change.changed_by_user_id, change.new_user_type)
        for change in _history_rows(store)
    ] == [(alice_id, "author")]
