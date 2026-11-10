"""User types: their order, the minimum-type check, and stored types at sign-in."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from policyengine_api.data.v2.models import User, UserType
from policyengine_api.services.v2.identity.services import (
    find_principal_user_in_session,
    resolve_principal_user_for_read_in_session,
    resolve_principal_user_in_session,
)
from policyengine_api.services.v2.identity.types import AccountConversionOutcome
from policyengine_api.services.v2.identity.validators import (
    user_type_meets_minimum,
)
from policyengine_api.services.v2.user_accounts.database_session import (
    AccountDatabaseSession,
)
from policyengine_api.services.v2.user_accounts.services import V2AccountService
from policyengine_api.services.v2.user_policies.database_session import (
    UserPolicyDatabaseSession,
)
from policyengine_api.services.v2.user_policies.services import V2UserPolicyService
from policyengine_api.services.v2.user_policies.types import UserPolicyCreateFields
from tests.unit.v2.user_service_support import (
    ALICE,
    SIGNED_OUT_BROWSER,
    V2Store,
    default_legacy_references,
    v2_store,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from uuid import UUID

SIGNED_IN_TYPES_ABOVE_STANDARD = (UserType.AUTHOR, UserType.ADMIN)


def _never_build_the_auth0_deleter():
    msg = "these tests delete no account"
    raise AssertionError(msg)


@pytest.fixture
def store() -> Iterator[V2Store]:
    with v2_store() as isolated_store:
        yield isolated_store


def _accounts(store: V2Store) -> V2AccountService:
    return V2AccountService(
        AccountDatabaseSession(store.sessions),
        auth0_user_deleter_factory=_never_build_the_auth0_deleter,
    )


def _set_stored_type(store: V2Store, user_id: UUID, user_type: UserType) -> None:
    with store.sessions.begin() as session:
        user = session.get(User, user_id)
        assert user is not None
        user.user_type = user_type.value


def _stored_type(store: V2Store, user_id: UUID) -> str:
    with store.sessions() as session:
        user = session.get(User, user_id)
        assert user is not None
        return user.user_type


def test_user_types_run_from_unauthenticated_to_admin() -> None:
    assert [user_type.value for user_type in UserType] == [
        "unauthenticated",
        "standard",
        "author",
        "admin",
    ]


@pytest.mark.parametrize(
    ("user_type", "minimum", "meets_minimum"),
    [
        (UserType.UNAUTHENTICATED, UserType.UNAUTHENTICATED, True),
        (UserType.UNAUTHENTICATED, UserType.STANDARD, False),
        (UserType.STANDARD, UserType.STANDARD, True),
        (UserType.STANDARD, UserType.AUTHOR, False),
        (UserType.AUTHOR, UserType.STANDARD, True),
        (UserType.AUTHOR, UserType.AUTHOR, True),
        (UserType.AUTHOR, UserType.ADMIN, False),
        (UserType.ADMIN, UserType.UNAUTHENTICATED, True),
        (UserType.ADMIN, UserType.AUTHOR, True),
        (UserType.ADMIN, UserType.ADMIN, True),
    ],
)
def test_a_user_type_meets_every_minimum_at_or_below_it(
    user_type: UserType,
    minimum: UserType,
    meets_minimum: bool,  # noqa: FBT001  # pytest passes parameters positionally
) -> None:
    assert user_type_meets_minimum(user_type, minimum) is meets_minimum


def test_users_store_each_signed_in_type_and_refuse_unknown_types(
    store: V2Store,
) -> None:
    with store.sessions.begin() as session:
        for user_type in SIGNED_IN_TYPES_ABOVE_STANDARD:
            session.add(User(user_type=user_type.value, primary_country="us"))
    with Session(store.sessions.kw["bind"]) as session:
        session.add(User(user_type="editor", primary_country="us"))
        with pytest.raises(IntegrityError):
            session.commit()
    with Session(store.sessions.kw["bind"]) as session:
        # Every signed-in type still needs a primary country.
        session.add(User(user_type=UserType.AUTHOR.value))
        with pytest.raises(IntegrityError):
            session.commit()


@pytest.mark.parametrize("user_type", SIGNED_IN_TYPES_ABOVE_STANDARD)
def test_a_signed_in_user_resolves_with_its_stored_type(
    store: V2Store, user_type: UserType
) -> None:
    account = _accounts(store).get_account(principal=ALICE, country_id="us")
    _set_stored_type(store, account.id, user_type)

    with store.sessions.begin() as session:
        found = find_principal_user_in_session(session, ALICE)
        resolved = resolve_principal_user_in_session(session, ALICE, country_id="uk")
        resolved_for_read = resolve_principal_user_for_read_in_session(
            session, ALICE, country_id="uk"
        )

    assert found is not None
    assert resolved_for_read is not None
    assert {found.user_type, resolved.user_type, resolved_for_read.user_type} == {
        user_type
    }
    assert {found.user_id, resolved.user_id, resolved_for_read.user_id} == {account.id}


def test_a_first_sign_in_resolves_as_standard(store: V2Store) -> None:
    with store.sessions.begin() as session:
        resolved = resolve_principal_user_in_session(session, ALICE, country_id="us")

    assert resolved.user_type is UserType.STANDARD
    assert _stored_type(store, resolved.user_id) == "standard"


@pytest.mark.parametrize("user_type", SIGNED_IN_TYPES_ABOVE_STANDARD)
def test_signing_in_again_keeps_an_author_or_admin_type(
    store: V2Store, user_type: UserType
) -> None:
    accounts = _accounts(store)
    account = accounts.get_account(principal=ALICE, country_id="us")
    _set_stored_type(store, account.id, user_type)

    again = accounts.get_account(principal=ALICE, country_id="uk")

    assert (again.id, again.user_type) == (account.id, user_type.value)
    assert _stored_type(store, account.id) == user_type.value


@pytest.mark.parametrize("user_type", SIGNED_IN_TYPES_ABOVE_STANDARD)
def test_an_upgrade_into_an_author_or_admin_keeps_its_type(
    store: V2Store, user_type: UserType
) -> None:
    accounts = _accounts(store)
    account = accounts.get_account(principal=ALICE, country_id="us")
    _set_stored_type(store, account.id, user_type)
    V2UserPolicyService(
        UserPolicyDatabaseSession(store.sessions), default_legacy_references()
    ).create_user_policy(
        principal=SIGNED_OUT_BROWSER,
        association_input=UserPolicyCreateFields(country_id="us", legacy_policy_id=1),
    )

    merged = accounts.upgrade_account(
        principal=ALICE,
        unauthenticated_user_id=SIGNED_OUT_BROWSER.user_id,
        country_id="us",
    )
    without_browser_user = accounts.upgrade_account(
        principal=ALICE,
        unauthenticated_user_id=SIGNED_OUT_BROWSER.user_id,
        country_id="us",
    )

    assert merged.outcome is AccountConversionOutcome.MERGED
    assert without_browser_user.outcome is AccountConversionOutcome.NONE
    assert {merged.account.user_type, without_browser_user.account.user_type} == {
        user_type.value
    }
    assert _stored_type(store, account.id) == user_type.value
