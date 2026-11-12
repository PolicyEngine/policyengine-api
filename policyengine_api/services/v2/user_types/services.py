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

Every change, every invitation write and every signed-in account deletion
first takes one transaction-scoped advisory lock, then reads the admins and
checks the caller or the deleted user against them, so they run one at a time
and none can leave no admin. After a change commits, the user is emailed about
it when an email service is configured.

With a user profile source, admins see each user's email and names as Auth0
has them, read after the database work and never stored: only identities
from the users' issuer are looked up, and an email search also finds users
through Auth0. When Auth0 can't answer, reads keep the stored values and
record a warning, and an email search is refused. A type change commits
before its response reads Auth0.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError

from policyengine_api.data.v2.models import UserType, UserTypeChangeSource
from policyengine_api.libs.rate_limit_wait_budget import RateLimitWaitBudget
from policyengine_api.services.v2.identity.services import (
    find_principal_user_in_session,
)
from policyengine_api.services.v2.user_emails.types import (
    SignInIdentity,
    UserTypeChangeEmail,
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
    admin_user_read_with_profiles,
    caller_user_type,
    identities_by_user,
    profiles_of,
    stored_admin_user,
    stored_user_type_change,
    user_type_change_read_with_profiles,
)
from policyengine_api.services.v2.user_types.types import (
    MAXIMUM_EMAIL_SEARCH_MATCHES,
    AdminUserPage,
    AdminUserRead,
    AdminUserSearch,
    IdentitySubjects,
    RequestedUserType,
    ScriptedUserTypeChange,
    StoredAdminUser,
    UserTypeChangeOrigin,
    UserTypeChangeRead,
)
from policyengine_api.services.v2.user_types.validators import (
    AdminUserProfilesUnavailableError,
    UserTypeCheckUnavailableError,
    require_admin_after_deletion,
    require_another_admin,
    require_email_search_within_limit,
    require_expected_user_type,
    require_listed_admin,
    require_minimum_user_type,
    require_one_user_with_email,
    require_searchable_email_text,
    require_signed_in_user,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping
    from uuid import UUID

    from sqlmodel import Session

    from policyengine_api.data.v2.models import User, UserIdentity, UserTypeChange
    from policyengine_api.libs.auth0_management import Auth0UserProfile
    from policyengine_api.services.v2.identity.types import AccountPrincipal
    from policyengine_api.services.v2.user_emails.services import V2UserEmailService
    from policyengine_api.services.v2.user_types.database_session import (
        UserTypeDatabaseSession,
    )
    from policyengine_api.services.v2.user_types.types import UserProfileSource

logger = logging.getLogger(__name__)

PROFILES_UNAVAILABLE_EVENT = "admin_user_profiles_unavailable"
EMAIL_SEARCH_UNAVAILABLE_MESSAGE = (
    "Users can't be searched by email now: their emails could not be read "
    "from Auth0. Try again shortly."
)
PROFILES_UNREADABLE_MESSAGE = "Users' emails and names could not be read from Auth0"
# A recorded cause is a short identifier such as http_403 or timeout, so no
# email address or subject can pass as one.
SAFE_CAUSE_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,39}")


def _safe_cause(error: Exception) -> str:
    """Return the cause the profile reader's error names, else ``unknown``.

    The reader's errors carry a ``cause`` such as an HTTP status
    (``http_403``, ``http_429``), ``timeout``, ``connection_error`` or
    ``unreadable_answer``.
    """
    cause = getattr(error, "cause", None)
    if isinstance(cause, str) and SAFE_CAUSE_PATTERN.fullmatch(cause):
        return cause
    return "unknown"


def _record_profiles_unavailable(
    operation: str, error: Exception, *, cause: str | None = None
) -> None:
    """Record why Auth0 couldn't answer, by error type and safe cause only.

    An error's message may name a subject or an email, so it is left out.
    """
    logger.warning(
        PROFILES_UNAVAILABLE_EVENT,
        extra={
            "policyengine_attributes": {
                "operation": operation,
                "error_type": type(error).__name__,
                "cause": _safe_cause(error) if cause is None else cause,
            }
        },
    )


class V2UserTypeService:
    """Sequence user-type checks and changes through explicit sessions."""

    def __init__(
        self,
        database_session: UserTypeDatabaseSession,
        *,
        user_profile_source_factory: (
            Callable[[], UserProfileSource | None] | None
        ) = None,
        user_email_service: V2UserEmailService | None = None,
    ) -> None:
        """Open every session through ``database_session``.

        ``user_profile_source_factory`` is called once by each admin read or
        change; without it, or when it returns None, admins see stored emails
        and names only, and an email search reads only stored emails.
        ``user_email_service`` emails each user whose type changed, after the
        commit; without it nobody is emailed.
        """
        self._database_session = database_session
        self._user_profile_source_factory = user_profile_source_factory
        self._user_email_service = user_email_service

    def _email_type_change(self, change: UserTypeChangeEmail | None) -> None:
        """Email the user about a committed change; never raises for a failure."""
        if change is not None and self._user_email_service is not None:
            self._user_email_service.send_type_change(change)

    def _profile_source(self) -> UserProfileSource | None:
        """Return the configured profile source, or None when there is none.

        Raise AdminUserProfilesUnavailableError when its settings are unusable.
        """
        if self._user_profile_source_factory is None:
            return None
        try:
            return self._user_profile_source_factory()
        except Exception as error:
            _record_profiles_unavailable("configure", error, cause="invalid_settings")
            raise AdminUserProfilesUnavailableError(
                EMAIL_SEARCH_UNAVAILABLE_MESSAGE
            ) from error

    def _profile_source_for_reads(self) -> UserProfileSource | None:
        """Return the profile source, or None when it is absent or unusable."""
        try:
            return self._profile_source()
        except AdminUserProfilesUnavailableError:
            # Reads answer with stored values; the failure is recorded.
            return None

    def _email_matching_identities(
        self,
        principal: AccountPrincipal,
        source: UserProfileSource,
        text: str,
        wait_budget: RateLimitWaitBudget,
    ) -> IdentitySubjects:
        """Return the users' subjects whose Auth0 email contains ``text``.

        Only an admin's search reaches Auth0. Raise
        AdminUserProfilesUnavailableError when Auth0 can't answer, and
        AdminUserEmailSearchRefusedError when more than 200 users match.
        """
        with self._database_session.read() as session:
            _require_caller_type(session, principal, UserType.ADMIN)
        try:
            found = source.reader.search_user_ids_by_email(
                text,
                match_limit=MAXIMUM_EMAIL_SEARCH_MATCHES,
                wait_budget=wait_budget,
            )
        except Exception as error:
            _record_profiles_unavailable("search_by_email", error)
            raise AdminUserProfilesUnavailableError(
                EMAIL_SEARCH_UNAVAILABLE_MESSAGE
            ) from error
        return IdentitySubjects(
            issuer=source.issuer, subjects=require_email_search_within_limit(found)
        )

    def _read_profiles(
        self,
        source: UserProfileSource,
        subjects: tuple[str, ...],
        wait_budget: RateLimitWaitBudget,
    ) -> Mapping[str, Auth0UserProfile]:
        """Raise AdminUserProfilesUnavailableError when Auth0 can't answer."""
        try:
            return source.reader.read_user_profiles(subjects, wait_budget=wait_budget)
        except Exception as error:
            _record_profiles_unavailable("read_profiles", error)
            raise AdminUserProfilesUnavailableError(
                PROFILES_UNREADABLE_MESSAGE
            ) from error

    def _profiles(
        self,
        source: UserProfileSource | None,
        subjects: Iterable[str],
        wait_budget: RateLimitWaitBudget,
    ) -> Mapping[str, Auth0UserProfile]:
        """Read these subjects' profiles in one call to the reader.

        Return none when there is no source or subject, or when Auth0 can't
        answer: admins then see stored values.
        """
        unique_subjects = tuple(dict.fromkeys(subjects))
        if source is None or not unique_subjects:
            return {}
        try:
            return self._read_profiles(source, unique_subjects, wait_budget)
        except AdminUserProfilesUnavailableError:
            return {}

    def _with_profiles(
        self,
        source: UserProfileSource | None,
        stored: Iterable[StoredAdminUser],
        wait_budget: RateLimitWaitBudget,
    ) -> tuple[AdminUserRead, ...]:
        """Fill stored users' emails and names from Auth0, after the database."""
        users = tuple(stored)
        profiles = self._profiles(
            source,
            (subject for user in users for subject in user.profile_subjects),
            wait_budget,
        )
        return tuple(
            admin_user_read_with_profiles(
                user.read, profiles_of(user.profile_subjects, profiles)
            )
            for user in users
        )

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
        """Return one page of signed-in users, newest first, to an admin.

        With a profile source, an email search also finds users whose Auth0
        email matches; raise AdminUserProfilesUnavailableError when Auth0
        can't answer it. Raise AdminUserEmailSearchRefusedError for search
        text with ``<`` or ``>``, before any Auth0 call, and for text more
        than 200 Auth0 users match.
        """
        email_matching_identities = None
        if search.email is None:
            source = self._profile_source_for_reads()
        else:
            require_searchable_email_text(search.email)
            source = self._profile_source()
        # Every Auth0 call of this admin request waits from one budget.
        wait_budget = RateLimitWaitBudget()
        if search.email is not None and source is not None:
            email_matching_identities = self._email_matching_identities(
                principal, source, search.email, wait_budget
            )
        issuer = None if source is None else source.issuer
        with self._database_session.read() as session:
            _require_caller_type(session, principal, UserType.ADMIN)
            users = read_signed_in_users(
                session,
                email_contains=search.email,
                offset=search.offset,
                limit=search.limit + 1,
                email_matching_identities=email_matching_identities,
            )
            stored = _stored_admin_users(session, users[: search.limit], issuer)
        return AdminUserPage(
            items=self._with_profiles(source, stored, wait_budget),
            offset=search.offset,
            limit=search.limit,
            has_more=len(users) > search.limit,
        )

    def get_user(self, *, principal: AccountPrincipal, user_id: UUID) -> AdminUserRead:
        """Return one signed-in user to an admin."""
        source = self._profile_source_for_reads()
        issuer = None if source is None else source.issuer
        with self._database_session.read() as session:
            _require_caller_type(session, principal, UserType.ADMIN)
            user = require_signed_in_user(read_signed_in_user(session, user_id))
            stored = _stored_admin_users(session, [user], issuer)
        (read,) = self._with_profiles(source, stored, RateLimitWaitBudget())
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
        The change commits before Auth0 is read for the response.
        """
        source = self._profile_source_for_reads()
        issuer = None if source is None else source.issuer
        with self._database_session.transaction() as session:
            caller = find_principal_user_in_session(session, principal)
            caller_user_id = None if caller is None else caller.user_id
            acquire_user_type_change_lock(session)
            admin_user_ids = read_admin_user_ids(session)
            require_listed_admin(caller_user_id, admin_user_ids)
            user = require_signed_in_user(
                read_signed_in_user(session, user_id, for_update=True)
            )
            change = _change_type_in_session(
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
            stored = _stored_admin_users(session, [user], issuer)
        self._email_type_change(change)
        (read,) = self._with_profiles(source, stored, RateLimitWaitBudget())
        return read

    def list_user_type_changes(
        self, *, principal: AccountPrincipal, user_id: UUID
    ) -> tuple[UserTypeChangeRead, ...]:
        """Return a signed-in user's recorded type changes, newest first.

        Each change names its admin by the admin's Auth0 email when there is
        a profile source, else by the stored one.
        """
        source = self._profile_source_for_reads()
        issuer = None if source is None else source.issuer
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

            stored = tuple(
                stored_user_type_change(change, *admin_of(change), issuer)
                for change in changes
            )
        profiles = self._profiles(
            source,
            (
                subject
                for change in stored
                for subject in change.changed_by_profile_subjects
            ),
            RateLimitWaitBudget(),
        )
        return tuple(
            user_type_change_read_with_profiles(
                change.read, profiles_of(change.changed_by_profile_subjects, profiles)
            )
            for change in stored
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
            change = _change_type_in_session(
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
        self._email_type_change(change)
        return ScriptedUserTypeChange(user=read, previous_user_type=previous_user_type)


def lock_and_require_admin_in_session(
    session: Session, principal: AccountPrincipal
) -> UUID:
    """Take the user-type change lock, then return the caller's ID if an admin.

    The caller is checked against the admins read after the lock, as a type
    change checks it. Raise UserTypeBelowMinimumError otherwise.
    """
    caller = find_principal_user_in_session(session, principal)
    acquire_user_type_change_lock(session)
    return require_listed_admin(
        None if caller is None else caller.user_id, read_admin_user_ids(session)
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


def _stored_admin_users(
    session: Session, users: list[User], issuer: str | None
) -> tuple[StoredAdminUser, ...]:
    """Describe users as stored, with their subjects from ``issuer``."""
    identities = identities_by_user(
        read_identities_newest_first(session, [user.id for user in users])
    )
    return tuple(
        stored_admin_user(user, identities.get(user.id, []), issuer) for user in users
    )


def _change_type_in_session(
    session: Session,
    user: User,
    *,
    requested: RequestedUserType,
    admin_user_ids: list[UUID],
    origin: UserTypeChangeOrigin,
) -> UserTypeChangeEmail | None:
    """Change the type, unless the user already has it, and record the change.

    When ``requested`` names the type its requester last read, the user's
    stored type must still be that one. Return the email to send the user
    once the change commits, or None when nothing changed.
    """
    previous_user_type = UserType(user.user_type)
    user_type = requested.user_type
    if previous_user_type is user_type:
        return None
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
    return UserTypeChangeEmail(
        user_id=user.id,
        previous_user_type=previous_user_type,
        user_type=user_type,
        identities=tuple(
            SignInIdentity(issuer=identity.issuer, subject=identity.subject)
            for identity in read_identities_newest_first(session, [user.id])
        ),
    )
