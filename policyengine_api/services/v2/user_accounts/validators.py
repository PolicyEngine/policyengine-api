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
    """Raised when account data was removed but the Auth0 user was not."""


class AccountDeletionUnavailableError(RuntimeError):
    """Raised before any data is deleted when Auth0 deletion cannot run."""


def require_resolved_account(owner: ResolvedUser | None) -> ResolvedUser:
    """An unauthenticated principal has no account until its first write."""
    if owner is None:
        raise AccountNotFoundError("The account was not found")
    return owner


def require_account(user: User | None) -> User:
    if user is None:
        raise AccountNotFoundError("The account was not found")
    return user


def require_editable_account(principal: AccountPrincipal) -> UserPrincipal:
    if not isinstance(principal, UserPrincipal):
        raise AccountEditRequiresSignInError("Sign in to edit your account details.")
    return principal
