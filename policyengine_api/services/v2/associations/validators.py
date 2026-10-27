"""Typed failures shared by user-owned association resources."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.economy_reports.types import (
    SimulationServiceUnavailableError,
)

if TYPE_CHECKING:
    from uuid import UUID

    from policyengine_api.services.v2.associations.types import (
        LegacyReferenceChecker,
        SimulationReferenceChecker,
    )


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


class SimulationReferenceCheckUnavailableError(SimulationServiceUnavailableError):
    """The service was built without the v2 report and simulation checker."""


def require_simulation_reference_checker(
    simulation_references: SimulationReferenceChecker | None,
) -> SimulationReferenceChecker:
    """Return the checker, or raise SimulationReferenceCheckUnavailableError."""
    if simulation_references is None:
        msg = "v2 report and simulation references cannot be checked here"
        raise SimulationReferenceCheckUnavailableError(msg)
    return simulation_references


def require_not_mirror_owned(*, mirror_owned: bool, association_id: UUID) -> None:
    """Raise MirrorOwnedAssociationError if the v1 saved-policy mirror owns the row."""
    if mirror_owned:
        msg = (
            f"association {association_id} is maintained from v1 saved policies "
            "and cannot be changed here"
        )
        raise MirrorOwnedAssociationError(msg)
