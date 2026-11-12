"""Database-independent validation for v2 identity resolution."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.data.v2.models import User, UserType

if TYPE_CHECKING:
    from policyengine_api.services.v2.identity.types import StoredIdentity

USER_TYPES_BY_PERMISSION = tuple(UserType)


class IdentityProvisioningError(RuntimeError):
    """Raised when a concurrent provisioning conflict leaves no stored identity."""


class StandardUserRequiresSignInError(PermissionError):
    """Raised when an unauthenticated credential names a signed-in user.

    An unauthenticated principal never acts on a signed-in user of any type,
    including one converted from the same browser's unauthenticated user.
    """


def require_concurrent_identity(identity: StoredIdentity | None) -> StoredIdentity:
    """Return the identity a concurrent request stored, or raise if it is absent.

    Raise IdentityProvisioningError when a lost provisioning race finds no row.
    """
    if identity is None:
        msg = "user identity provisioning conflict did not resolve to a stored row"
        raise IdentityProvisioningError(msg)
    return identity


def user_type_meets_minimum(user_type: UserType, minimum: UserType) -> bool:
    """Whether ``user_type`` has every permission of ``minimum``.

    Each type has every permission of the types before it in ``UserType``.
    """
    return USER_TYPES_BY_PERMISSION.index(user_type) >= (
        USER_TYPES_BY_PERMISSION.index(minimum)
    )


def is_unauthenticated_user(user: User) -> bool:
    """Whether the user belongs to a signed-out browser rather than an identity."""
    return user.user_type == UserType.UNAUTHENTICATED


def require_unauthenticated_user(user: User | None) -> User | None:
    """Pass through an absent or unauthenticated user; refuse a signed-in one."""
    if user is not None and not is_unauthenticated_user(user):
        msg = (
            "This browser's saved work now belongs to a signed-in account; "
            "sign in to continue"
        )
        raise StandardUserRequiresSignInError(msg)
    return user


def require_provisioned_user(user: User | None) -> User:
    """Return the provisioned user, or raise IdentityProvisioningError if None."""
    if user is None:
        msg = "unauthenticated user provisioning did not resolve to a stored row"
        raise IdentityProvisioningError(msg)
    return user
