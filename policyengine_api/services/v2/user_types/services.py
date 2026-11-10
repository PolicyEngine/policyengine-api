"""Minimum user types, and admins' and the type script's changes to users' types.

A caller's type is its stored user's type. A signed-in caller with no user
yet is standard, and a signed-out browser is unauthenticated. Checking a
caller's type only reads: it never provisions a user.

Only admins list signed-in users, read one, change a user's type or read a
user's recorded type changes. An admin's change also names the type the admin
last read: a change to another type is refused when the stored type is no
longer that one. Only the type is compared, so a type changed and changed back
since the read is not detected, and asking for the type the user already has
changes nothing whatever was expected. Unauthenticated users are never listed or
changed, since their IDs are their browsers' credentials. Each change records
the previous and new type, who made it and how. A change that would leave no
admin is refused.

Every change, and every signed-in account deletion, first takes one
transaction-scoped advisory lock, then reads the admins and checks the caller
or the deleted user against them, so they run one at a time and none can leave
no admin.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError

from policyengine_api.data.v2.models import UserType, UserTypeChangeSource
from policyengine_api.services.v2.identity.services import (
    find_principal_user_in_session,
)
from policyengine_api.services.v2.user_types.database_connectors.creates import (
    create_user_type_change,
)
from policyengine_api.services.v2.user_types.database_connectors.reads import (
    acquire_user_type_change_lock,
    read_admin_user_ids,
    read_identities_newest_first,
    read_signed_in_user,
    read_signed_in_users,
    read_signed_in_users_with_email,
    read_user_type_changes,
    read_users,
)
from policyengine_api.services.v2.user_types.database_connectors.updates import (
    update_user_type,
)
from policyengine_api.services.v2.user_types.transformations import (
    admin_user_read,
    caller_user_type,
    identities_by_user,
    user_type_change_read,
)
from policyengine_api.services.v2.user_types.types import (
    AdminUserPage,
    AdminUserRead,
    AdminUserSearch,
    RequestedUserType,
    ScriptedUserTypeChange,
    UserTypeChangeOrigin,
    UserTypeChangeRead,
)
from policyengine_api.services.v2.user_types.validators import (
    UserTypeCheckUnavailableError,
    require_admin_after_deletion,
    require_another_admin,
    require_expected_user_type,
    require_listed_admin,
    require_minimum_user_type,
    require_one_user_with_email,
    require_signed_in_user,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlmodel import Session

    from policyengine_api.data.v2.models import User, UserIdentity, UserTypeChange
    from policyengine_api.services.v2.identity.types import AccountPrincipal
    from policyengine_api.services.v2.user_types.database_session import (
        UserTypeDatabaseSession,
    )


class V2UserTypeService:
    """Sequence user-type checks and changes through explicit sessions."""

    def __init__(self, database_session: UserTypeDatabaseSession) -> None:
        """Open every session through ``database_session``."""
        self._database_session = database_session

    def require_minimum_user_type(
        self, *, principal: AccountPrincipal, minimum: UserType
    ) -> UserType:
        """Return the caller's type, or raise UserTypeBelowMinimumError below it.

        Raise UserTypeCheckUnavailableError when the database can't be read.
        """
        try:
            with self._database_session.read() as session:
                resolved = find_principal_user_in_session(session, principal)
        except SQLAlchemyError as error:
            msg = "The caller's user type could not be read"
            raise UserTypeCheckUnavailableError(msg) from error
        return require_minimum_user_type(caller_user_type(principal, resolved), minimum)

    def list_users(
        self, *, principal: AccountPrincipal, search: AdminUserSearch
    ) -> AdminUserPage:
        """Return one page of signed-in users, newest first, to an admin."""
        with self._database_session.read() as session:
            _require_caller_type(session, principal, UserType.ADMIN)
            users = read_signed_in_users(
                session,
                email_contains=search.email,
                offset=search.offset,
                limit=search.limit + 1,
            )
            page = users[: search.limit]
            return AdminUserPage(
                items=_admin_user_reads(session, page),
                offset=search.offset,
                limit=search.limit,
                has_more=len(users) > search.limit,
            )

    def get_user(self, *, principal: AccountPrincipal, user_id: UUID) -> AdminUserRead:
        """Return one signed-in user to an admin."""
        with self._database_session.read() as session:
            _require_caller_type(session, principal, UserType.ADMIN)
            user = require_signed_in_user(read_signed_in_user(session, user_id))
            (read,) = _admin_user_reads(session, [user])
            return read

    def change_user_type(
        self,
        *,
        principal: AccountPrincipal,
        user_id: UUID,
        user_type: UserType,
        expected_user_type: UserType,
    ) -> AdminUserRead:
        """Change a signed-in user's type for an admin, recording the change.

        Setting the type the user already has changes and records nothing,
        whatever ``expected_user_type`` is. Otherwise the user's stored type
        must still be ``expected_user_type``, the type the admin last read;
        raise UserTypeChangedError if it isn't. The check compares types only,
        so a type changed and changed back since the read is not detected.
        """
        with self._database_session.transaction() as session:
            caller = find_principal_user_in_session(session, principal)
            caller_user_id = None if caller is None else caller.user_id
            acquire_user_type_change_lock(session)
            admin_user_ids = read_admin_user_ids(session)
            require_listed_admin(caller_user_id, admin_user_ids)
            user = require_signed_in_user(
                read_signed_in_user(session, user_id, for_update=True)
            )
            _change_type_in_session(
                session,
                user,
                requested=RequestedUserType(
                    user_type=user_type, expected_user_type=expected_user_type
                ),
                admin_user_ids=admin_user_ids,
                origin=UserTypeChangeOrigin(
                    changed_by_user_id=caller_user_id,
                    source=UserTypeChangeSource.ADMIN_ROUTE,
                ),
            )
            (read,) = _admin_user_reads(session, [user])
            return read

    def list_user_type_changes(
        self, *, principal: AccountPrincipal, user_id: UUID
    ) -> tuple[UserTypeChangeRead, ...]:
        """Return a signed-in user's recorded type changes, newest first."""
        with self._database_session.read() as session:
            _require_caller_type(session, principal, UserType.ADMIN)
            require_signed_in_user(read_signed_in_user(session, user_id))
            changes = read_user_type_changes(session, user_id)
            admin_ids = {
                change.changed_by_user_id
                for change in changes
                if change.changed_by_user_id is not None
            }
            admins = {user.id: user for user in read_users(session, admin_ids)}
            admin_identities = identities_by_user(
                read_identities_newest_first(session, admin_ids)
            )

            def admin_of(
                change: UserTypeChange,
            ) -> tuple[User | None, list[UserIdentity]]:
                if change.changed_by_user_id is None:
                    return None, []
                return (
                    admins.get(change.changed_by_user_id),
                    admin_identities.get(change.changed_by_user_id, []),
                )

            return tuple(
                user_type_change_read(change, *admin_of(change)) for change in changes
            )

    def set_user_type_by_email(
        self, *, email: str, user_type: UserType
    ) -> ScriptedUserTypeChange:
        """Set the type of the one signed-in user with ``email``, for the script.

        Raise UserEmailMatchError unless exactly one signed-in user has that
        whole email address. The change is recorded with no admin.
        """
        with self._database_session.transaction() as session:
            acquire_user_type_change_lock(session)
            admin_user_ids = read_admin_user_ids(session)
            matched = require_one_user_with_email(
                read_signed_in_users_with_email(session, email), email
            )
            user = require_signed_in_user(
                read_signed_in_user(session, matched.id, for_update=True)
            )
            previous_user_type = UserType(user.user_type)
            _change_type_in_session(
                session,
                user,
                requested=RequestedUserType(
                    user_type=user_type, expected_user_type=None
                ),
                admin_user_ids=admin_user_ids,
                origin=UserTypeChangeOrigin(
                    changed_by_user_id=None, source=UserTypeChangeSource.SCRIPT
                ),
            )
            (read,) = _admin_user_reads(session, [user])
            return ScriptedUserTypeChange(
                user=read, previous_user_type=previous_user_type
            )


def require_admin_remains_after_deletion_in_session(
    session: Session, *, user_id: UUID
) -> None:
    """Take the user-type change lock, then refuse to delete the only admin.

    Account deletion calls this for every signed-in user before deleting it.
    It takes the user-type change lock, as a type change does, and checks the
    user against the admins read after it, not against a type read earlier,
    so a deletion and a concurrent change or deletion can't together leave no
    admin.
    """
    acquire_user_type_change_lock(session)
    require_admin_after_deletion(
        user_id=user_id, admin_user_ids=read_admin_user_ids(session)
    )


def _require_caller_type(
    session: Session, principal: AccountPrincipal, minimum: UserType
) -> UserType:
    resolved = find_principal_user_in_session(session, principal)
    return require_minimum_user_type(caller_user_type(principal, resolved), minimum)


def _admin_user_reads(session: Session, users: list[User]) -> tuple[AdminUserRead, ...]:
    identities = identities_by_user(
        read_identities_newest_first(session, [user.id for user in users])
    )
    return tuple(admin_user_read(user, identities.get(user.id, [])) for user in users)


def _change_type_in_session(
    session: Session,
    user: User,
    *,
    requested: RequestedUserType,
    admin_user_ids: list[UUID],
    origin: UserTypeChangeOrigin,
) -> None:
    """Change the type, unless the user already has it, and record the change.

    When ``requested`` names the type its requester last read, the user's
    stored type must still be that one.
    """
    previous_user_type = UserType(user.user_type)
    user_type = requested.user_type
    if previous_user_type is user_type:
        return
    if requested.expected_user_type is not None:
        require_expected_user_type(
            current_user_type=previous_user_type,
            expected_user_type=requested.expected_user_type,
        )
    require_another_admin(
        previous_user_type=previous_user_type,
        new_user_type=user_type,
        admin_user_ids=admin_user_ids,
    )
    update_user_type(session, user, user_type=user_type)
    create_user_type_change(
        session,
        user_id=user.id,
        previous_user_type=previous_user_type,
        new_user_type=user_type,
        origin=origin,
    )
