"""Database-independent validation for v2 identity resolution."""

from __future__ import annotations

from policyengine_api.data.v2.models import User, UserIdentity, UserType


class IdentityProvisioningError(RuntimeError):
    """Raised when a concurrent provisioning conflict leaves no stored identity."""


class StandardUserRequiresSignInError(PermissionError):
    """Raised when an unauthenticated credential names a standard user.

    An unauthenticated principal never acts on a standard user, including one
    converted from the same browser's unauthenticated user.
    """


def require_concurrent_identity(identity: UserIdentity | None) -> UserIdentity:
    if identity is None:
        raise IdentityProvisioningError(
            "user identity provisioning conflict did not resolve to a stored row"
        )
    return identity


def is_unauthenticated_user(user: User) -> bool:
    return user.user_type == UserType.UNAUTHENTICATED


def require_unauthenticated_user(user: User | None) -> User | None:
    """Pass through an absent or unauthenticated user; refuse a standard one."""

    if user is not None and not is_unauthenticated_user(user):
        raise StandardUserRequiresSignInError(
            "This browser's saved work now belongs to a signed-in account; "
            "sign in to continue"
        )
    return user


def require_provisioned_user(user: User | None) -> User:
    if user is None:
        raise IdentityProvisioningError(
            "unauthenticated user provisioning did not resolve to a stored row"
        )
    return user
