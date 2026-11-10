"""PostgreSQL tests for admins' changes to users' types, as the runtime role.

These prove what SQLite cannot: the runtime role's declared privileges cover
the changes and their history, the user-type change lock makes concurrent
changes and deletions run one at a time so the last admin is never demoted or
deleted, and account deletion cascades through the history or keeps a change
without its admin.
"""

from __future__ import annotations

import os
import threading
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, delete, select, update
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session

from policyengine_api.data.v2.migration_target import (
    V2_ALEMBIC_DISPOSABLE_TEST,
    load_v2_alembic_settings,
)
from policyengine_api.data.v2.models import (
    LegacyUserMapping,
    User,
    UserIdentity,
    UserType,
    UserTypeChange,
)
from policyengine_api.data.v2.settings import V2_MIGRATION_DATABASE_URL
from policyengine_api.services.v2.identity.types import UserPrincipal
from policyengine_api.services.v2.user_accounts.database_session import (
    AccountDatabaseSession,
)
from policyengine_api.services.v2.user_accounts.services import V2AccountService
from policyengine_api.services.v2.user_types.database_connectors.reads import (
    acquire_user_type_change_lock,
    read_admin_user_ids,
    read_signed_in_user,
)
from policyengine_api.services.v2.user_types.database_connectors.updates import (
    update_user_type,
)
from policyengine_api.services.v2.user_types.database_session import (
    UserTypeDatabaseSession,
)
from policyengine_api.services.v2.user_types.services import V2UserTypeService
from policyengine_api.services.v2.user_types.types import AdminUserSearch
from policyengine_api.services.v2.user_types.validators import (
    LastAdminDeletionError,
    UserTypeBelowMinimumError,
    UserTypeChangedError,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

# Long enough for a change or deletion not blocked by the held lock to finish.
LOCK_WAIT_SECONDS = 1.0


def _disposable_url() -> str:
    database_url = os.environ.get(V2_MIGRATION_DATABASE_URL, "")
    if not database_url:
        pytest.skip(f"{V2_MIGRATION_DATABASE_URL} is not set")
    settings = load_v2_alembic_settings(
        {
            V2_MIGRATION_DATABASE_URL: database_url,
            V2_ALEMBIC_DISPOSABLE_TEST: os.environ.get(V2_ALEMBIC_DISPOSABLE_TEST, ""),
        }
    )
    if not settings.disposable_test:
        pytest.fail("user type persistence tests require disposable-test mode")
    return settings.url.render_as_string(hide_password=False)


@pytest.fixture
def sessions(managed_v2_roles, v2_engine_as_role) -> Iterator[sessionmaker[Session]]:
    """Open sessions as the Public API's runtime role; clean up as the superuser.

    The database may hold other tests' admins, so each test starts with none
    and puts them back afterwards.
    """
    runtime_engine = v2_engine_as_role(
        managed_v2_roles.runtime, pool_size=5, max_overflow=5
    )
    cleanup_engine = create_engine(_disposable_url())
    factory = sessionmaker(runtime_engine, class_=Session, expire_on_commit=False)
    issuer = f"https://user-types-{uuid4().hex[:12]}.example.test/"
    factory.kw["info"] = {"issuer": issuer}
    with cleanup_engine.begin() as connection:
        other_admins = list(
            connection.execute(
                select(User.id).where(User.user_type == UserType.ADMIN.value)
            ).scalars()
        )
        if other_admins:
            connection.execute(
                update(User)
                .where(User.id.in_(other_admins))
                .values(user_type=UserType.STANDARD.value)
            )
    try:
        yield factory
    finally:
        with cleanup_engine.begin() as connection:
            owned = select(UserIdentity.user_id).where(UserIdentity.issuer == issuer)
            user_ids = list(connection.execute(owned).scalars())
            if user_ids:
                connection.execute(
                    delete(LegacyUserMapping).where(
                        LegacyUserMapping.user_id.in_(user_ids)
                    )
                )
                connection.execute(delete(User).where(User.id.in_(user_ids)))
            if other_admins:
                connection.execute(
                    update(User)
                    .where(User.id.in_(other_admins))
                    .values(user_type=UserType.ADMIN.value)
                )
        runtime_engine.dispose()
        cleanup_engine.dispose()


def _principal(sessions, name: str) -> UserPrincipal:
    return UserPrincipal(
        issuer=sessions.kw["info"]["issuer"],
        subject=f"google-oauth2|{name}",
        email=f"{name}@user-types.example.test",
    )


def _accounts(sessions) -> V2AccountService:
    return V2AccountService(AccountDatabaseSession(sessions))


def _user_types(sessions) -> V2UserTypeService:
    return V2UserTypeService(UserTypeDatabaseSession(sessions))


def _store_type_as_superuser(user_id: UUID, user_type: UserType) -> None:
    engine = create_engine(_disposable_url())
    try:
        with engine.begin() as connection:
            connection.execute(
                update(User).where(User.id == user_id).values(user_type=user_type.value)
            )
    finally:
        engine.dispose()


def _stored_types(sessions, user_ids: list[UUID]) -> list[str]:
    with sessions() as session:
        return [session.get(User, user_id).user_type for user_id in user_ids]


def _history(sessions, user_id: UUID) -> list[UserTypeChange]:
    with sessions() as session:
        return list(
            session.execute(
                select(UserTypeChange).where(UserTypeChange.user_id == user_id)
            ).scalars()
        )


def test_the_runtime_role_changes_types_and_records_them(sessions) -> None:
    alice = _principal(sessions, "alice")
    bob = _principal(sessions, "bob")
    accounts = _accounts(sessions)
    alice_id = accounts.get_account(principal=alice, country_id="us").id
    bob_id = accounts.get_account(principal=bob, country_id="uk").id
    _store_type_as_superuser(alice_id, UserType.ADMIN)
    user_types = _user_types(sessions)

    promoted = user_types.change_user_type(
        principal=alice,
        user_id=bob_id,
        user_type=UserType.AUTHOR,
        expected_user_type=UserType.STANDARD,
    )
    found = user_types.list_users(
        principal=alice,
        search=AdminUserSearch(email="bob@USER-TYPES"),
    )
    scripted = user_types.set_user_type_by_email(
        email=bob.email, user_type=UserType.ADMIN
    )
    history = user_types.list_user_type_changes(principal=alice, user_id=bob_id)

    assert promoted.user_type is UserType.AUTHOR
    assert [user.id for user in found.items] == [bob_id]
    assert scripted.previous_user_type is UserType.AUTHOR
    assert _stored_types(sessions, [alice_id, bob_id]) == ["admin", "admin"]
    assert [
        (change.previous_user_type, change.new_user_type, change.changed_by_user_id)
        for change in history
    ] == [
        (UserType.AUTHOR, UserType.ADMIN, None),
        (UserType.STANDARD, UserType.AUTHOR, alice_id),
    ]


def test_a_change_waits_for_another_and_never_demotes_the_last_admin(
    sessions,
) -> None:
    """Alice demotes Bob while Bob's demotion of Alice waits for the lock."""
    alice = _principal(sessions, "alice")
    bob = _principal(sessions, "bob")
    accounts = _accounts(sessions)
    alice_id = accounts.get_account(principal=alice, country_id="us").id
    bob_id = accounts.get_account(principal=bob, country_id="us").id
    for user_id in (alice_id, bob_id):
        _store_type_as_superuser(user_id, UserType.ADMIN)
    outcomes: dict[str, object] = {}
    finished = threading.Event()

    def bob_demotes_alice() -> None:
        try:
            outcomes["result"] = _user_types(sessions).change_user_type(
                principal=bob,
                user_id=alice_id,
                user_type=UserType.STANDARD,
                expected_user_type=UserType.ADMIN,
            )
        except Exception as error:  # noqa: BLE001  # the test inspects the failure
            outcomes["error"] = error
        finally:
            finished.set()

    held = sessions()
    try:
        held.begin()
        # Alice's change holds the user-type change lock, as the service's does.
        assert sorted(_lock_and_read_admins(held)) == sorted([alice_id, bob_id])
        waiting_change = threading.Thread(target=bob_demotes_alice)
        waiting_change.start()
        assert not finished.wait(LOCK_WAIT_SECONDS)
        bob_row = read_signed_in_user(held, bob_id, for_update=True)
        assert bob_row is not None
        update_user_type(held, bob_row, user_type=UserType.STANDARD)
        held.commit()
    finally:
        held.close()
    waiting_change.join(timeout=10)

    # Bob is no longer an admin once his turn comes, so his change is refused.
    assert isinstance(outcomes.get("error"), UserTypeBelowMinimumError)
    assert _stored_types(sessions, [alice_id, bob_id]) == ["admin", "standard"]


def test_deleting_accounts_removes_or_keeps_their_recorded_changes(sessions) -> None:
    alice = _principal(sessions, "alice")
    bob = _principal(sessions, "bob")
    carol = _principal(sessions, "carol")
    accounts = _accounts(sessions)
    alice_id = accounts.get_account(principal=alice, country_id="us").id
    bob_id = accounts.get_account(principal=bob, country_id="us").id
    carol_id = accounts.get_account(principal=carol, country_id="us").id
    _store_type_as_superuser(carol_id, UserType.ADMIN)
    user_types = _user_types(sessions)
    for user_id in (alice_id, bob_id):
        user_types.change_user_type(
            principal=carol,
            user_id=user_id,
            user_type=UserType.ADMIN,
            expected_user_type=UserType.STANDARD,
        )

    # Bob's own deletion removes his history; Carol's keeps the change she
    # made to Alice, without her.
    accounts.delete_account(principal=bob)
    accounts.delete_account(principal=carol)

    assert _history(sessions, bob_id) == []
    (alice_change,) = _history(sessions, alice_id)
    assert (alice_change.new_user_type, alice_change.changed_by_user_id) == (
        "admin",
        None,
    )


def _lock_and_read_admins(session: Session) -> list[UUID]:
    """Take the user-type change lock, as a change in progress does."""
    acquire_user_type_change_lock(session)
    return read_admin_user_ids(session)


def _delete_account_in_thread(sessions, principal, outcomes) -> threading.Thread:
    finished = threading.Event()
    outcomes["finished"] = finished

    def delete_account() -> None:
        try:
            _accounts(sessions).delete_account(principal=principal)
            outcomes["deleted"] = True
        except Exception as error:  # noqa: BLE001  # the test inspects the failure
            outcomes["error"] = error
        finally:
            finished.set()

    thread = threading.Thread(target=delete_account)
    thread.start()
    return thread


def _admin_ids(sessions) -> list[UUID]:
    with sessions() as session:
        return list(
            session.execute(
                select(User.id).where(User.user_type == UserType.ADMIN.value)
            ).scalars()
        )


def test_a_deletion_waits_for_a_promotion_and_never_removes_the_last_admin(
    sessions,
) -> None:
    """Olivia, standard, deletes her account while Xavier makes her the only admin."""
    olivia = _principal(sessions, "olivia")
    xavier = _principal(sessions, "xavier")
    accounts = _accounts(sessions)
    olivia_id = accounts.get_account(principal=olivia, country_id="us").id
    xavier_id = accounts.get_account(principal=xavier, country_id="us").id
    _store_type_as_superuser(xavier_id, UserType.ADMIN)
    outcomes: dict[str, object] = {}

    held = sessions()
    try:
        held.begin()
        # Xavier's change holds the user-type change lock and promotes Olivia.
        assert _lock_and_read_admins(held) == [xavier_id]
        olivia_row = read_signed_in_user(held, olivia_id, for_update=True)
        assert olivia_row is not None
        update_user_type(held, olivia_row, user_type=UserType.ADMIN)
        deletion = _delete_account_in_thread(sessions, olivia, outcomes)
        assert not outcomes["finished"].wait(LOCK_WAIT_SECONDS)
        # Then Xavier gives up his own admin type, leaving Olivia the only one.
        xavier_row = read_signed_in_user(held, xavier_id, for_update=True)
        assert xavier_row is not None
        update_user_type(held, xavier_row, user_type=UserType.STANDARD)
        held.commit()
    finally:
        held.close()
    deletion.join(timeout=10)

    assert isinstance(outcomes.get("error"), LastAdminDeletionError)
    assert _admin_ids(sessions) == [olivia_id]


def test_a_deletion_after_a_demotion_is_allowed_while_another_admin_remains(
    sessions,
) -> None:
    """Xavier demotes Olivia while her deletion waits; she is then deleted."""
    olivia = _principal(sessions, "olivia")
    xavier = _principal(sessions, "xavier")
    accounts = _accounts(sessions)
    olivia_id = accounts.get_account(principal=olivia, country_id="us").id
    xavier_id = accounts.get_account(principal=xavier, country_id="us").id
    for user_id in (olivia_id, xavier_id):
        _store_type_as_superuser(user_id, UserType.ADMIN)
    outcomes: dict[str, object] = {}

    held = sessions()
    try:
        held.begin()
        assert sorted(_lock_and_read_admins(held)) == sorted([olivia_id, xavier_id])
        olivia_row = read_signed_in_user(held, olivia_id, for_update=True)
        assert olivia_row is not None
        update_user_type(held, olivia_row, user_type=UserType.STANDARD)
        deletion = _delete_account_in_thread(sessions, olivia, outcomes)
        assert not outcomes["finished"].wait(LOCK_WAIT_SECONDS)
        held.commit()
    finally:
        held.close()
    deletion.join(timeout=10)

    assert outcomes.get("error") is None
    assert outcomes.get("deleted") is True
    assert _admin_ids(sessions) == [xavier_id]


def test_a_change_from_a_type_changed_while_it_waited_is_refused(sessions) -> None:
    """Carol read Bob as standard; Alice makes him an author while Carol waits."""
    alice = _principal(sessions, "alice")
    carol = _principal(sessions, "carol")
    bob = _principal(sessions, "bob")
    accounts = _accounts(sessions)
    alice_id = accounts.get_account(principal=alice, country_id="us").id
    carol_id = accounts.get_account(principal=carol, country_id="us").id
    bob_id = accounts.get_account(principal=bob, country_id="us").id
    for user_id in (alice_id, carol_id):
        _store_type_as_superuser(user_id, UserType.ADMIN)
    outcomes: dict[str, object] = {}
    finished = threading.Event()

    def carol_promotes_bob() -> None:
        try:
            outcomes["result"] = _user_types(sessions).change_user_type(
                principal=carol,
                user_id=bob_id,
                user_type=UserType.ADMIN,
                expected_user_type=UserType.STANDARD,
            )
        except Exception as error:  # noqa: BLE001  # the test inspects the failure
            outcomes["error"] = error
        finally:
            finished.set()

    held = sessions()
    try:
        held.begin()
        # Alice's change holds the user-type change lock and makes Bob an author.
        _lock_and_read_admins(held)
        bob_row = read_signed_in_user(held, bob_id, for_update=True)
        assert bob_row is not None
        update_user_type(held, bob_row, user_type=UserType.AUTHOR)
        waiting_change = threading.Thread(target=carol_promotes_bob)
        waiting_change.start()
        assert not finished.wait(LOCK_WAIT_SECONDS)
        held.commit()
    finally:
        held.close()
    waiting_change.join(timeout=10)

    assert isinstance(outcomes.get("error"), UserTypeChangedError)
    assert _stored_types(sessions, [bob_id]) == ["author"]
    assert _history(sessions, bob_id) == []
