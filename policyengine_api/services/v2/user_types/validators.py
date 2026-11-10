"""Database-independent checks for minimum user types and changes to users' types."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.data.v2.models import UserType
from policyengine_api.services.v2.identity.validators import user_type_meets_minimum

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence
    from uuid import UUID

    from policyengine_api.data.v2.models import User

BELOW_MINIMUM_MESSAGES = {
    UserType.STANDARD: "Sign in to do this",
    UserType.AUTHOR: "Only authors and admins may do this",
    UserType.ADMIN: "Only admins may do this",
}


class UserTypeBelowMinimumError(PermissionError):
    """Raised when the caller's user type is below what an operation requires (403)."""


class SignedInUserNotFoundError(LookupError):
    """Raised when no signed-in user has the requested ID (404).

    An unauthenticated user's ID is its browser's credential, so admins can
    neither see nor change one: it is reported as not found.
    """


class LastAdminDemotionError(ValueError):
    """Raised when a change would leave no admin (409)."""


class UserTypeChangedError(ValueError):
    """Raised when a user's type is no longer the one the admin expected (409)."""


class LastAdminDeletionError(ValueError):
    """Raised when deleting an account would leave no admin (409)."""


class UserTypeCheckUnavailableError(RuntimeError):
    """Raised when the caller's type can't be read from the database (503)."""


class UserEmailMatchError(LookupError):
    """Raised when the type script finds no signed-in user, or several, by email."""


def require_minimum_user_type(user_type: UserType, minimum: UserType) -> UserType:
    """Return ``user_type`` if it meets ``minimum``; raise otherwise."""
    if user_type_meets_minimum(user_type, minimum):
        return user_type
    raise UserTypeBelowMinimumError(BELOW_MINIMUM_MESSAGES[minimum])


def require_listed_admin(
    caller_user_id: UUID | None, admin_user_ids: Collection[UUID]
) -> None:
    """Refuse a caller who isn't among the admins read in this transaction."""
    if caller_user_id is None or caller_user_id not in admin_user_ids:
        raise UserTypeBelowMinimumError(BELOW_MINIMUM_MESSAGES[UserType.ADMIN])


def require_signed_in_user(user: User | None) -> User:
    """Return a signed-in user, or raise SignedInUserNotFoundError for None."""
    if user is None:
        msg = "No signed-in user has this ID"
        raise SignedInUserNotFoundError(msg)
    return user


def require_expected_user_type(
    *, current_user_type: UserType, expected_user_type: UserType
) -> None:
    """Refuse a change made from a type that is no longer the user's."""
    if current_user_type is not expected_user_type:
        msg = (
            f"This user's type is now {current_user_type.value}, not "
            f"{expected_user_type.value}. Nothing was changed."
        )
        raise UserTypeChangedError(msg)


def require_another_admin(
    *,
    previous_user_type: UserType,
    new_user_type: UserType,
    admin_user_ids: Collection[UUID],
) -> None:
    """Refuse to demote an admin when no other admin would remain."""
    demotes_an_admin = (
        previous_user_type is UserType.ADMIN and new_user_type is not UserType.ADMIN
    )
    if demotes_an_admin and len(admin_user_ids) <= 1:
        msg = "The last admin can't be demoted; make another user an admin first"
        raise LastAdminDemotionError(msg)


def require_admin_after_deletion(
    *, user_id: UUID, admin_user_ids: Collection[UUID]
) -> None:
    """Refuse to delete the only admin among the admins read after the lock."""
    if user_id in admin_user_ids and len(admin_user_ids) <= 1:
        msg = (
            "The last admin's account can't be deleted; make another user an "
            "admin first"
        )
        raise LastAdminDeletionError(msg)


def require_one_user_with_email(users: Sequence[User], email: str) -> User:
    """Return the one signed-in user with ``email``, or raise UserEmailMatchError."""
    if not users:
        msg = f"no signed-in user has the email {email}"
        raise UserEmailMatchError(msg)
    if len(users) > 1:
        msg = (
            f"{len(users)} signed-in users have the email {email}; change their "
            "types through the admin routes, which name users by ID"
        )
        raise UserEmailMatchError(msg)
    return users[0]
