"""Service tests for admins' deletion of signed-in users' accounts."""

from __future__ import annotations

import logging
import subprocess
import sys
from typing import TYPE_CHECKING
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session, select

from policyengine_api import observability
from policyengine_api.data.v2.models import (
    LegacyUserMapping,
    User,
    UserIdentity,
    UserPolicy,
    UserType,
)
from policyengine_api.services.v2.identity.types import UserPrincipal
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
from policyengine_api.services.v2.user_types.services import (
    require_admin_may_delete_user_in_session,
)
from policyengine_api.services.v2.user_types.validators import (
    LastAdminDeletionError,
    SignedInUserNotFoundError,
    UserTypeBelowMinimumError,
)
from tests.unit.v2.user_service_support import (
    ALICE,
    BOB,
    ISSUER,
    OTHER_SIGNED_OUT_BROWSER,
    SIGNED_OUT_BROWSER,
    V2Store,
    default_legacy_references,
    v2_store,
)

if TYPE_CHECKING:
    from collections.abc import Collection, Iterator

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
DANA_FROM_ANOTHER_TENANT = UserPrincipal(
    issuer=OTHER_TENANT_ISSUER, subject="auth0|dana", email="dana@example.test"
)
ACCOUNT_SERVICE_LOGGER = "policyengine_api.services.v2.user_accounts.services"
ABSENT_USER_ID = UUID("00000000-0000-0000-0000-0000000000a1")
ADMIN_DELETION_EVENT = "admin_deleted_v2_user_account"


class RecordingAuth0Users:
    """Stand in for the Auth0 deleter: count preparations, record deletions.

    ``deletion_error`` is raised for every subject, or only for
    ``failing_subjects`` when they are given.
    """

    def __init__(
        self,
        *,
        preparation_error: Exception | None = None,
        deletion_error: Exception | None = None,
        failing_subjects: Collection[str] | None = None,
    ) -> None:
        self.preparation_error = preparation_error
        self.deletion_error = deletion_error
        self.failing_subjects = failing_subjects
        self.preparations = 0
        self.attempted_subjects: list[str] = []
        self.deleted_subjects: list[str] = []

    def prepare_deletion(self) -> None:
        self.preparations += 1
        if self.preparation_error is not None:
            raise self.preparation_error

    def delete_user(self, subject: str) -> None:
        self.attempted_subjects.append(subject)
        fails = self.failing_subjects is None or subject in self.failing_subjects
        if self.deletion_error is not None and fails:
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
    monkeypatch.setattr(observability, "get_runtime", lambda: recording_runtime)
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

    with pytest.raises(AccountIdentityDeletionError) as failure:
        accounts.delete_user_account_as_admin(principal=ALICE, user_id=bob_id)

    assert failure.value.undeleted_auth0_user_count == 1
    assert "remain (1 of 1)" in str(failure.value)
    assert "by the person's email" in str(failure.value)
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


def test_loading_the_account_service_leaves_the_observability_runtime_unbuilt() -> None:
    """Loading the account service mustn't build the observability runtime.

    Importing ``policyengine_api.observability`` builds the process-wide
    runtime, which adds a root log handler and, with no OTLP endpoint, writes
    an ERROR record, so any command that loads the service would write them.
    """
    import_check = (
        "import sys\n"
        "import policyengine_api.services.v2.user_accounts.services\n"
        "loaded = 'policyengine_api.observability' in sys.modules\n"
        "assert not loaded, 'the observability runtime was imported'\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", import_check],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def _account_service_warnings(
    caplog: pytest.LogCaptureFixture,
) -> list[tuple[str, dict[str, object]]]:
    return [
        (record.getMessage(), record.policyengine_attributes)
        for record in caplog.records
        if record.name == ACCOUNT_SERVICE_LOGGER and record.levelno == logging.WARNING
    ]


@pytest.mark.usefixtures("runtime")
@pytest.mark.parametrize("deleted_by", ["bob", "an_admin"])
def test_every_auth0_user_is_tried_before_a_failure_is_reported(
    store: V2Store, caplog: pytest.LogCaptureFixture, deleted_by: str
) -> None:
    """Bob's first Auth0 user fails to delete, as after a rate limit."""
    caplog.set_level(logging.WARNING, logger=ACCOUNT_SERVICE_LOGGER)
    _sign_in(store, ALICE, UserType.ADMIN)
    bob_id = _sign_in(store, BOB)
    _give_bob_saved_work_and_more_identities(store, bob_id)
    auth0_users = RecordingAuth0Users(
        deletion_error=RuntimeError("rate limited"), failing_subjects={BOB.subject}
    )
    accounts = _accounts(store, auth0_users)

    def delete_bob() -> AccountDeletion:
        if deleted_by == "bob":
            return accounts.delete_account(principal=BOB)
        return accounts.delete_user_account_as_admin(principal=ALICE, user_id=bob_id)

    with pytest.raises(AccountIdentityDeletionError) as failure:
        delete_bob()

    assert auth0_users.attempted_subjects == [BOB.subject, BOB_LINKED_SUBJECT]
    assert auth0_users.deleted_subjects == [BOB_LINKED_SUBJECT]
    assert failure.value.undeleted_auth0_user_count == 1
    if deleted_by == "bob":
        # DELETE /v2/me keeps its message.
        assert str(failure.value) == (
            "Account data was deleted but the sign-in account could not be "
            "removed; retry the request"
        )
    else:
        assert "remain (1 of 2)" in str(failure.value)
        assert "by the person's email" in str(failure.value)
    assert _user_type_of(store, bob_id) is None
    assert _account_service_warnings(caplog) == [
        (
            "auth0_user_deletion_failed",
            {
                "v2_user_id": str(bob_id),
                "error_type": "RuntimeError",
                "auth0_user_count": 2,
                "undeleted_auth0_user_count": 1,
            },
        )
    ]


@pytest.mark.usefixtures("runtime")
def test_an_admin_deletion_logs_that_no_identity_was_under_the_issuer(
    store: V2Store, caplog: pytest.LogCaptureFixture
) -> None:
    """Dana signed in through another tenant, whose users this one can't delete."""
    caplog.set_level(logging.WARNING, logger=ACCOUNT_SERVICE_LOGGER)
    _sign_in(store, ALICE, UserType.ADMIN)
    dana_id = _sign_in(store, DANA_FROM_ANOTHER_TENANT)
    auth0_users = RecordingAuth0Users()

    deletion = _accounts(store, auth0_users).delete_user_account_as_admin(
        principal=ALICE, user_id=dana_id
    )

    assert deletion == AccountDeletion(user_id=dana_id, auth0_subjects=())
    assert auth0_users.attempted_subjects == []
    assert _user_type_of(store, dana_id) is None
    assert _account_service_warnings(caplog) == [
        (
            "auth0_user_deletion_skipped_no_identity_under_issuer",
            {"v2_user_id": str(dana_id)},
        )
    ]


@pytest.mark.parametrize("target", ["absent", "unauthenticated"])
@pytest.mark.parametrize("caller", ["standard", "author", "signed_out"])
def test_callers_below_admin_are_refused_before_the_target_is_looked_up(
    store: V2Store, runtime: RecordingRuntime, caller: str, target: str
) -> None:
    """A caller below admin gets 403 whether or not the target exists.

    The router refuses these callers first, so only this shows that the
    deletion's own check, in its transaction, looks at the caller before the
    target: an unauthenticated user's ID never answers differently from an
    absent one.
    """
    _sign_in(store, ALICE, UserType.ADMIN)
    _sign_in(store, BOB)
    _sign_in(store, CAROL, UserType.AUTHOR)
    _save_policy(store, SIGNED_OUT_BROWSER)
    _save_policy(store, OTHER_SIGNED_OUT_BROWSER)
    target_id = (
        ABSENT_USER_ID if target == "absent" else OTHER_SIGNED_OUT_BROWSER.user_id
    )
    auth0_users = RecordingAuth0Users()

    def attempt_deletion() -> None:
        if caller == "signed_out":
            # The service takes only signed-in principals, since admins are
            # signed in; the check it runs takes any caller.
            with store.sessions.begin() as session:
                require_admin_may_delete_user_in_session(
                    session, principal=SIGNED_OUT_BROWSER, user_id=target_id
                )
            return
        _accounts(store, auth0_users).delete_user_account_as_admin(
            principal=BOB if caller == "standard" else CAROL, user_id=target_id
        )

    with pytest.raises(UserTypeBelowMinimumError, match="Only admins"):
        attempt_deletion()

    assert _user_type_of(store, OTHER_SIGNED_OUT_BROWSER.user_id) == "unauthenticated"
    with store.sessions() as session:
        assert len(session.exec(select(UserPolicy)).all()) == 2
    assert auth0_users.attempted_subjects == []
    assert runtime.events == []


def test_a_failed_commit_records_no_deletion_and_deletes_no_auth0_user(
    store: V2Store, runtime: RecordingRuntime
) -> None:
    _sign_in(store, ALICE, UserType.ADMIN)
    bob_id = _sign_in(store, BOB)
    refusing_sessions = sessionmaker(
        store.sessions.kw["bind"], class_=Session, expire_on_commit=False
    )

    @sa.event.listens_for(refusing_sessions, "before_commit")
    def refuse_commit(_session: Session) -> None:
        msg = "COMMIT"
        raise OperationalError(msg, {}, Exception("the connection was lost"))

    auth0_users = RecordingAuth0Users()
    accounts = V2AccountService(
        AccountDatabaseSession(refusing_sessions),
        auth0_user_deleter_factory=lambda: auth0_users,
    )

    with pytest.raises(OperationalError):
        accounts.delete_user_account_as_admin(principal=ALICE, user_id=bob_id)

    assert _user_type_of(store, bob_id) == "standard"
    assert auth0_users.preparations == 1
    assert auth0_users.attempted_subjects == []
    assert runtime.events == []
