"""Database-independent validation for v2 account operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.identity.types import (
    AccountPrincipal,
    ResolvedUser,
    UserPrincipal,
)

if TYPE_CHECKING:
    from policyengine_api.data.v2.models import User, UserTypeChange


class AccountNotFoundError(LookupError):
    """Raised when the principal has no stored account."""


class AccountEditRequiresSignInError(PermissionError):
    """Raised when an unauthenticated principal edits account details."""


class AccountIdentityDeletionError(RuntimeError):
    """Raised when account data was removed but the Auth0 user was not."""


class AccountDeletionUnavailableError(RuntimeError):
    """Raised before any data is deleted when Auth0 deletion cannot run."""


class TypeChangeNotFoundError(LookupError):
    """Raised when the caller has no recorded type change with an ID (404)."""


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


def require_type_change(change: UserTypeChange | None) -> UserTypeChange:
    """Return the caller's recorded type change, or raise TypeChangeNotFoundError."""
    if change is None:
        msg = "You have no type change with this ID"
        raise TypeChangeNotFoundError(msg)
    return change
