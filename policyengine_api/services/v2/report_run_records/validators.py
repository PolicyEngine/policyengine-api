"""Errors of the report-run record service."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID


class ReportRunRecordStorageError(RuntimeError):
    """The detailed-save database could not be read or written for a record."""


class RequesterUserGoneError(LookupError):
    """The user found before the simulation service was asked no longer exists.

    A signed-out browser's user is deleted when signing in merges it into an
    existing account, and any user by its own account deletion. Its UUID now
    names nobody, so the request is not recorded rather than recorded for a
    user re-created with that ID.
    """


def require_requester_user(user_id: UUID, *, exists: bool) -> UUID:
    """Return the user's ID, or raise RequesterUserGoneError once it is gone."""
    if not exists:
        msg = "The requesting user no longer exists, so the request was not recorded"
        raise RequesterUserGoneError(msg)
    return user_id
