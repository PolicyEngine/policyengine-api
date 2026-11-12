"""Typed failures shared by user-owned association resources."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from policyengine_api.services.v2.associations.types import LegacyReferenceChecker


class AssociationNotFoundError(LookupError):
    """The association is absent, in another country, or owned by another user."""


class AssociationReferenceConflictError(ValueError):
    """The supplied references or countries contradict each other."""


class AssociationConflictError(RuntimeError):
    """The requested change conflicts with stored association state."""


class MirrorOwnedAssociationError(AssociationConflictError):
    """The association is maintained by the Stage 10 v1 saved-policy mirror."""


class AssociationLinkNotFoundError(LookupError):
    """A linked association is absent or not owned by the same user and country."""


class LegacyReferenceCheckUnavailableError(RuntimeError):
    """The service was built without the read-only v1 reference checker."""


def require_legacy_reference_checker(
    legacy_references: LegacyReferenceChecker | None,
) -> LegacyReferenceChecker:
    """Return the checker, or raise LegacyReferenceCheckUnavailableError if None."""
    if legacy_references is None:
        msg = "v1 reference checks are not configured"
        raise LegacyReferenceCheckUnavailableError(msg)
    return legacy_references


def require_not_mirror_owned(*, mirror_owned: bool, association_id: UUID) -> None:
    """Raise MirrorOwnedAssociationError if the v1 saved-policy mirror owns the row."""
    if mirror_owned:
        msg = (
            f"association {association_id} is maintained from v1 saved policies "
            "and cannot be changed here"
        )
        raise MirrorOwnedAssociationError(msg)


def require_one_reference(
    kind: str, *, detailed_save_id: UUID | None, legacy_id: int | None
) -> None:
    """Raise AssociationReferenceConflictError when both references are named.

    v1 report and simulation numbers are not connected to detailed-save
    records, so a saved ``kind`` names one or the other; only the
    production migration writes records holding both.
    """
    if detailed_save_id is not None and legacy_id is not None:
        msg = (
            f"A saved {kind} names a detailed-save {kind} or a v1 {kind} "
            "number, not both"
        )
        raise AssociationReferenceConflictError(msg)


def violates_foreign_key(error: Exception, constraint_name: str) -> bool:
    """Return whether a database error is a violation of the named foreign key.

    That is SQLSTATE 23503 (``foreign_key_violation``) on ``constraint_name``,
    as psycopg reports it on the error SQLAlchemy wraps.
    """
    driver_error = getattr(error, "orig", None)
    diagnostics = getattr(driver_error, "diag", None)
    return (
        getattr(driver_error, "sqlstate", None) == "23503"
        and getattr(diagnostics, "constraint_name", None) == constraint_name
    )
