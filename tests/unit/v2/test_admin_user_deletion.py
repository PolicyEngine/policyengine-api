"""Service tests for admins' deletion of signed-in users' accounts."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import pytest
from sqlmodel import select

from policyengine_api.data.v2.models import (
    LegacyUserMapping,
    User,
    UserIdentity,
    UserPolicy,
    UserType,
)
from policyengine_api.services.v2.identity.types import UserPrincipal
from policyengine_api.services.v2.user_accounts import services as account_services
from policyengine_api.services.v2.user_accounts.database_session import (
    AccountDatabaseSession,
)
from policyengine_api.services.v2.user_accounts.services import V2AccountService
from policyengine_api.services.v2.user_accounts.types import AccountDeletion
from policyengine_api.services.v2.user_accounts.validators import (
    AccountDeletionUnavailableError,
    AccountIdentityDeletionError,
)
from policyengine_api.services.v2.user_policies.database_session import (
    UserPolicyDatabaseSession,
)
from policyengine_api.services.v2.user_policies.services import V2UserPolicyService
from policyengine_api.services.v2.user_policies.types import UserPolicyCreateFields
from policyengine_api.services.v2.user_types.validators import (
    LastAdminDeletionError,
    SignedInUserNotFoundError,
    UserTypeBelowMinimumError,
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

    from policyengine_api.services.v2.identity.types import AccountPrincipal

CAROL = UserPrincipal(issuer=ISSUER, subject="google-oauth2|carol")
ALICE_WITH_EMAIL = UserPrincipal(
    issuer=ISSUER, subject=ALICE.subject, email="alice@example.test"
)
BOB_WITH_EMAIL = UserPrincipal(
    issuer=ISSUER, subject=BOB.subject, email="bob@example.test"
)
BOB_LINKED_SUBJECT = "google-oauth2|bob-linked"
OTHER_TENANT_ISSUER = "https://other-tenant.example.test/"
ABSENT_USER_ID = UUID("00000000-0000-0000-0000-0000000000a1")
ADMIN_DELETION_EVENT = "admin_deleted_v2_user_account"


class RecordingAuth0Users:
    """Stand in for the Auth0 deleter: count preparations, record deletions."""

    def __init__(
        self,
        *,
        preparation_error: Exception | None = None,
        deletion_error: Exception | None = None,
    ) -> None:
        self.preparation_error = preparation_error
        self.deletion_error = deletion_error
        self.preparations = 0
        self.deleted_subjects: list[str] = []

    def prepare_deletion(self) -> None:
        self.preparations += 1
        if self.preparation_error is not None:
            raise self.preparation_error

    def delete_user(self, subject: str) -> None:
        if self.deletion_error is not None:
            raise self.deletion_error
        self.deleted_subjects.append(subject)


class RecordingRuntime:
    """Record the runtime events the account service emits."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, object]]] = []

    def event(
        self,
        name: str,
        *,
        severity: str = "INFO",
        attributes: dict[str, object] | None = None,
    ) -> None:
        self.events.append((name, severity, dict(attributes or {})))


@pytest.fixture
def store() -> Iterator[V2Store]:
    with v2_store() as isolated_store:
        yield isolated_store


@pytest.fixture
def runtime(monkeypatch) -> RecordingRuntime:
    recording_runtime = RecordingRuntime()
    monkeypatch.setattr(account_services, "get_runtime", lambda: recording_runtime)
    return recording_runtime


def _accounts(
    store: V2Store, auth0_users: RecordingAuth0Users | None = None
) -> V2AccountService:
    return V2AccountService(
        AccountDatabaseSession(store.sessions),
        auth0_user_deleter_factory=(
            None if auth0_users is None else (lambda: auth0_users)
        ),
    )


def _sign_in(
    store: V2Store,
    principal: UserPrincipal,
    user_type: UserType = UserType.STANDARD,
) -> UUID:
    user_id = _accounts(store).get_account(principal=principal, country_id="us").id
    if user_type is not UserType.STANDARD:
        with store.sessions.begin() as session:
            user = session.get(User, user_id)
            assert user is not None
            user.user_type = user_type.value
    return user_id


def _user_type_of(store: V2Store, user_id: UUID) -> str | None:
    with store.sessions() as session:
        user = session.get(User, user_id)
        return None if user is None else user.user_type


def _save_policy(store: V2Store, principal: AccountPrincipal) -> None:
    V2UserPolicyService(
        UserPolicyDatabaseSession(store.sessions), default_legacy_references()
    ).create_user_policy(
        principal=principal,
        association_input=UserPolicyCreateFields(country_id="us", legacy_policy_id=1),
    )


def _give_bob_saved_work_and_more_identities(store: V2Store, bob_id: UUID) -> None:
    """Give Bob a saved policy, a v1 user mapping and two more sign-in identities.

    One identity is from this tenant and one from another, whose Auth0 users
    this tenant's Management API can't delete.
    """
    _save_policy(store, BOB)
    with store.sessions.begin() as session:
        session.add(LegacyUserMapping(legacy_user_id="auth0|bob-v1", user_id=bob_id))
        session.add(
            UserIdentity(user_id=bob_id, issuer=ISSUER, subject=BOB_LINKED_SUBJECT)
        )
        session.add(
            UserIdentity(
                user_id=bob_id,
                issuer=OTHER_TENANT_ISSUER,
                subject="auth0|bob-other-tenant",
            )
        )


@pytest.mark.usefixtures("runtime")
@pytest.mark.parametrize("deleted_by", ["bob", "an_admin"])
def test_own_and_admin_deletions_remove_the_same_records_and_auth0_users(
    store: V2Store, deleted_by: str
) -> None:
    alice_id = _sign_in(store, ALICE, UserType.ADMIN)
    bob_id = _sign_in(store, BOB)
    _give_bob_saved_work_and_more_identities(store, bob_id)
    auth0_users = RecordingAuth0Users()
    accounts = _accounts(store, auth0_users)

    if deleted_by == "bob":
        deletion = accounts.delete_account(principal=BOB)
    else:
        deletion = accounts.delete_user_account_as_admin(
            principal=ALICE, user_id=bob_id
        )

    assert deletion == AccountDeletion(
        user_id=bob_id, auth0_subjects=(BOB.subject, BOB_LINKED_SUBJECT)
    )
    assert auth0_users.preparations == 1
    assert auth0_users.deleted_subjects == [BOB.subject, BOB_LINKED_SUBJECT]
    with store.sessions() as session:
        assert session.get(User, bob_id) is None
        assert session.exec(select(LegacyUserMapping)).all() == []
        assert session.exec(select(UserPolicy)).all() == []
        assert {
            identity.subject for identity in session.exec(select(UserIdentity))
        } == {ALICE.subject}
    assert _user_type_of(store, alice_id) == "admin"


def test_callers_below_admin_delete_nothing(
    store: V2Store, runtime: RecordingRuntime
) -> None:
    _sign_in(store, ALICE, UserType.AUTHOR)
    bob_id = _sign_in(store, BOB)
    auth0_users = RecordingAuth0Users()
    accounts = _accounts(store, auth0_users)

    # Carol has signed in but has no user yet, so she is standard.
    for principal in (ALICE, BOB, CAROL):
        with pytest.raises(UserTypeBelowMinimumError, match="Only admins"):
            accounts.delete_user_account_as_admin(principal=principal, user_id=bob_id)

    assert _user_type_of(store, bob_id) == "standard"
    assert auth0_users.deleted_subjects == []
    assert runtime.events == []
    with store.sessions() as session:
        # The refusal provisioned no user for Carol.
        assert {
            identity.subject for identity in session.exec(select(UserIdentity))
        } == {ALICE.subject, BOB.subject}


def test_absent_and_unauthenticated_user_ids_are_not_found(
    store: V2Store, runtime: RecordingRuntime
) -> None:
    _sign_in(store, ALICE, UserType.ADMIN)
    _save_policy(store, SIGNED_OUT_BROWSER)
    auth0_users = RecordingAuth0Users()
    accounts = _accounts(store, auth0_users)

    for user_id in (ABSENT_USER_ID, SIGNED_OUT_BROWSER.user_id):
        with pytest.raises(SignedInUserNotFoundError):
            accounts.delete_user_account_as_admin(principal=ALICE, user_id=user_id)

    assert _user_type_of(store, SIGNED_OUT_BROWSER.user_id) == "unauthenticated"
    with store.sessions() as session:
        assert len(session.exec(select(UserPolicy)).all()) == 1
    assert auth0_users.deleted_subjects == []
    assert runtime.events == []


def test_an_admin_deleting_their_own_account_keeps_the_last_admin(
    store: V2Store, runtime: RecordingRuntime
) -> None:
    alice_id = _sign_in(store, ALICE, UserType.ADMIN)
    auth0_users = RecordingAuth0Users()
    accounts = _accounts(store, auth0_users)

    with pytest.raises(LastAdminDeletionError, match="last admin"):
        accounts.delete_user_account_as_admin(principal=ALICE, user_id=alice_id)
    assert _user_type_of(store, alice_id) == "admin"
    assert auth0_users.deleted_subjects == []

    bob_id = _sign_in(store, BOB, UserType.ADMIN)
    deletion = accounts.delete_user_account_as_admin(principal=ALICE, user_id=alice_id)

    assert deletion == AccountDeletion(
        user_id=alice_id, auth0_subjects=(ALICE.subject,)
    )
    assert _user_type_of(store, alice_id) is None
    assert auth0_users.deleted_subjects == [ALICE.subject]
    # Bob is now the last admin.
    with pytest.raises(LastAdminDeletionError):
        accounts.delete_user_account_as_admin(principal=BOB, user_id=bob_id)
    assert _user_type_of(store, bob_id) == "admin"
    assert runtime.events == [
        (
            ADMIN_DELETION_EVENT,
            "INFO",
            {"admin_v2_user_id": str(alice_id), "v2_user_id": str(alice_id)},
        )
    ]


def test_each_admin_deletion_is_recorded_by_v2_user_ids_only(
    store: V2Store, runtime: RecordingRuntime
) -> None:
    alice_id = _sign_in(store, ALICE_WITH_EMAIL, UserType.ADMIN)
    bob_id = _sign_in(store, BOB_WITH_EMAIL)
    carol_id = _sign_in(store, CAROL)
    accounts = _accounts(store)

    accounts.delete_user_account_as_admin(principal=ALICE_WITH_EMAIL, user_id=bob_id)
    # Carol's own deletion records no admin's deletion.
    accounts.delete_account(principal=CAROL)

    assert runtime.events == [
        (
            ADMIN_DELETION_EVENT,
            "INFO",
            {"admin_v2_user_id": str(alice_id), "v2_user_id": str(bob_id)},
        )
    ]
    assert _user_type_of(store, carol_id) is None
    recorded_values = " ".join(str(value) for value in runtime.events[0][2].values())
    assert "@" not in recorded_values
    assert "google-oauth2" not in recorded_values


@pytest.mark.parametrize("failure", ["settings", "credentials"])
def test_unavailable_auth0_credentials_stop_an_admin_deletion_before_any_change(
    store: V2Store, runtime: RecordingRuntime, failure: str
) -> None:
    _sign_in(store, ALICE, UserType.ADMIN)
    bob_id = _sign_in(store, BOB)

    def unusable_settings() -> RecordingAuth0Users:
        msg = "AUTH0_MANAGEMENT_DOMAIN must be a bare host name"
        raise RuntimeError(msg)

    if failure == "settings":
        accounts = V2AccountService(
            AccountDatabaseSession(store.sessions),
            auth0_user_deleter_factory=unusable_settings,
        )
    else:
        accounts = _accounts(
            store,
            RecordingAuth0Users(preparation_error=RuntimeError("secret access denied")),
        )

    with pytest.raises(AccountDeletionUnavailableError, match="nothing was deleted"):
        accounts.delete_user_account_as_admin(principal=ALICE, user_id=bob_id)

    assert _user_type_of(store, bob_id) == "standard"
    assert runtime.events == []


def test_a_failed_auth0_deletion_after_an_admin_deletion_is_reported(
    store: V2Store, runtime: RecordingRuntime
) -> None:
    alice_id = _sign_in(store, ALICE, UserType.ADMIN)
    bob_id = _sign_in(store, BOB)
    accounts = _accounts(
        store, RecordingAuth0Users(deletion_error=RuntimeError("management api down"))
    )

    with pytest.raises(AccountIdentityDeletionError, match="remove them in Auth0"):
        accounts.delete_user_account_as_admin(principal=ALICE, user_id=bob_id)

    # The data is gone, so the deletion is recorded.
    assert _user_type_of(store, bob_id) is None
    assert runtime.events == [
        (
            ADMIN_DELETION_EVENT,
            "INFO",
            {"admin_v2_user_id": str(alice_id), "v2_user_id": str(bob_id)},
        )
    ]
    # A second request finds no user.
    with pytest.raises(SignedInUserNotFoundError):
        accounts.delete_user_account_as_admin(principal=ALICE, user_id=bob_id)


def test_an_admin_deletion_without_auth0_management_keeps_the_auth0_users(
    store: V2Store, runtime: RecordingRuntime
) -> None:
    _sign_in(store, ALICE, UserType.ADMIN)
    bob_id = _sign_in(store, BOB)

    deletion = _accounts(store).delete_user_account_as_admin(
        principal=ALICE, user_id=bob_id
    )

    assert deletion == AccountDeletion(user_id=bob_id, auth0_subjects=())
    assert _user_type_of(store, bob_id) is None
    assert [name for name, _severity, _attributes in runtime.events] == [
        ADMIN_DELETION_EVENT
    ]
