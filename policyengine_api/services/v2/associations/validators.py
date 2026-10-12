"""Typed failures shared by user-owned association resources."""

from __future__ import annotations

from uuid import UUID


class AssociationNotFoundError(LookupError):
    """The association is absent, in another country, or owned by another user."""


class AssociationReferenceConflictError(ValueError):
    """The supplied references or countries contradict each other."""


class AssociationConflictError(RuntimeError):
    """The requested change conflicts with stored association state."""


class MirrorOwnedAssociationError(AssociationConflictError):
    """The association is maintained by the Stage 10 v1 saved-policy mirror."""


class AssociationClientRefConflictError(AssociationConflictError):
    """The caller already has an association with the supplied client_ref."""


class AssociationLinkNotFoundError(LookupError):
    """A linked association is absent or not owned by the same user and country."""


def require_unused_client_ref(
    existing_id: UUID | None,
    *,
    client_ref: str,
) -> None:
    if existing_id is not None:
        raise AssociationClientRefConflictError(
            f"an association with client_ref {client_ref!r} already exists"
        )


def require_not_mirror_owned(mirror_owned: bool, *, association_id: UUID) -> None:
    if mirror_owned:
        raise MirrorOwnedAssociationError(
            f"association {association_id} is maintained from v1 saved policies "
            "and cannot be changed here"
        )
