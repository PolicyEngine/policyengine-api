"""Database-independent validation for v2 account operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.identity.types import (
    AccountPrincipal,
    ResolvedUser,
    UserPrincipal,
)

if TYPE_CHECKING:
    from policyengine_api.data.v2.models import User


class AccountNotFoundError(LookupError):
    """Raised when the principal has no stored account."""


class AccountEditRequiresSignInError(PermissionError):
    """Raised when an unauthenticated principal edits account details."""


class AccountIdentityDeletionError(RuntimeError):
    """Raised when account data was removed but some of its Auth0 users were not.

    ``undeleted_auth0_user_count`` is how many of them remain in Auth0.
    """

    def __init__(self, message: str, *, undeleted_auth0_user_count: int) -> None:
        """Keep ``message`` as the error's text and the count of remaining users."""
        super().__init__(message)
        self.undeleted_auth0_user_count = undeleted_auth0_user_count


class AccountDeletionUnavailableError(RuntimeError):
    """Raised before any data is deleted when Auth0 deletion cannot run."""


def require_resolved_account(owner: ResolvedUser | None) -> ResolvedUser:
    """Return the resolved user, or raise AccountNotFoundError if there is none.

    An unauthenticated principal has no account until its first write.
    """
    if owner is None:
        msg = "The account was not found"
        raise AccountNotFoundError(msg)
    return owner


def require_account(user: User | None) -> User:
    """Return the stored user, or raise AccountNotFoundError if it is None."""
    if user is None:
        msg = "The account was not found"
        raise AccountNotFoundError(msg)
    return user


def require_editable_account(principal: AccountPrincipal) -> UserPrincipal:
    """Return a signed-in principal, or raise AccountEditRequiresSignInError."""
    if not isinstance(principal, UserPrincipal):
        msg = "Sign in to edit your account details."
        raise AccountEditRequiresSignInError(msg)
    return principal
