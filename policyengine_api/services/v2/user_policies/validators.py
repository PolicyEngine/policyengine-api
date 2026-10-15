"""Database-independent validation for v2 user-policy operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.associations.validators import (
    AssociationNotFoundError,
    AssociationReferenceConflictError,
)
from policyengine_api.services.v2.user_policies.types import (
    LegacyUserPolicyMappingAction,
)

if TYPE_CHECKING:
    from uuid import UUID

    from policyengine_api.data.v2.models import (
        LegacyUserMapping,
        LegacyUserPolicyMapping,
        Policy,
        User,
        UserPolicy,
    )
    from policyengine_api.services.v2.policies.types import LegacyPolicySnapshot
    from policyengine_api.services.v2.user_policies.types import (
        LegacyUserPolicySnapshot,
        UserPolicyCreationInput,
    )


class UserPolicyNotFoundError(AssociationNotFoundError):
    """Raised when an association is absent for the caller and country."""


class AssociationPolicyNotFoundError(LookupError):
    """Raised when an association references an unknown policy UUID."""


class AssociationUserNotFoundError(LookupError):
    """Raised when an association references an unknown v2 user UUID."""


class AssociationCountryConflictError(AssociationReferenceConflictError):
    """Raised when an association and its referenced policy differ by country."""


class LegacyUserPolicyIntegrityError(RuntimeError):
    """Raised when source, policy, association, or mapping identity conflicts."""


def require_user_policy(
    association: UserPolicy | None, *, association_id: UUID
) -> UserPolicy:
    """Return the association, or raise UserPolicyNotFoundError if it is None."""
    if association is None:
        raise UserPolicyNotFoundError(
            f"user-policy association {association_id} was not found"
        )
    return association


def validate_association_policy(
    *,
    country_id: str,
    policy_id: UUID,
    policy: Policy | None,
) -> None:
    """Check that a referenced policy exists and is in the association's country.

    Raise AssociationPolicyNotFoundError or AssociationCountryConflictError.
    """
    if policy is None:
        raise AssociationPolicyNotFoundError(f"policy {policy_id} was not found")
    if policy.country_id != country_id:
        raise AssociationCountryConflictError(
            "Association country_id must match the referenced policy"
        )


def resolve_association_policy_id(
    *,
    requested_policy_id: UUID | None,
    mapped_policy_id: UUID | None,
) -> UUID | None:
    """Combine an explicit v2 reference with the v1 mapping, if both exist."""
    if (
        requested_policy_id is not None
        and mapped_policy_id is not None
        and requested_policy_id != mapped_policy_id
    ):
        raise AssociationReferenceConflictError(
            "policy_id does not match the policy mirrored from legacy_policy_id"
        )
    return requested_policy_id if requested_policy_id is not None else mapped_policy_id


def validate_existing_legacy_user_mapping(
    mapping: LegacyUserMapping, *, user: User | None
) -> UUID:
    """Return the mapped v2 user id, or raise if that user no longer exists."""
    if user is None:
        raise LegacyUserPolicyIntegrityError(
            "legacy user mapping has no referenced v2 user"
        )
    return mapping.user_id


def validate_legacy_user_mapping_conflict(
    mapping: LegacyUserMapping | None, *, user: User | None
) -> UUID:
    """Return the user id of the mapping that won the race, or raise if unusable."""
    if mapping is None or user is None:
        raise LegacyUserPolicyIntegrityError(
            "legacy user mapping conflict did not resolve to a v2 user"
        )
    return mapping.user_id


def validate_legacy_user_policy_input(
    snapshot: LegacyUserPolicySnapshot,
    reform_snapshot: LegacyPolicySnapshot,
    *,
    source_revision: int,
) -> None:
    """Require a positive revision and a saved policy that uses the reform snapshot."""
    if source_revision <= 0:
        raise LegacyUserPolicyIntegrityError(
            "legacy user-policy source revision must be positive"
        )
    if (
        snapshot.country_id != reform_snapshot.country_id
        or snapshot.reform_id != reform_snapshot.legacy_policy_id
    ):
        raise LegacyUserPolicyIntegrityError(
            "saved policy does not reference the supplied reform snapshot"
        )


def validate_existing_legacy_user_policy_mapping(
    mapping: LegacyUserPolicyMapping,
    *,
    association: UserPolicy | None,
    country_id: str,
    fingerprint: str,
    user_id: UUID,
    policy_id: UUID,
    source_revision: int,
    fingerprint_version: int,
) -> tuple[LegacyUserPolicyMappingAction, UserPolicy]:
    """Decide how to apply a v1 revision to an existing mapping.

    Return the action with the mapped association. Raise
    LegacyUserPolicyIntegrityError if the association is missing or its user,
    policy or country changed, if the fingerprint version differs, if a replay
    has a different fingerprint, or if a revision was skipped.
    """
    if association is None:
        raise LegacyUserPolicyIntegrityError(
            "legacy user-policy mapping has no association"
        )
    if (
        association.policy_id != policy_id
        or association.country_id != country_id
        or association.user_id != user_id
    ):
        raise LegacyUserPolicyIntegrityError(
            "legacy user-policy mapping conflicts with immutable association fields"
        )
    if mapping.fingerprint_version != fingerprint_version:
        raise LegacyUserPolicyIntegrityError(
            "legacy user-policy fingerprint version is unsupported"
        )
    if source_revision < mapping.last_applied_source_revision:
        return LegacyUserPolicyMappingAction.STALE, association
    if source_revision == mapping.last_applied_source_revision:
        if mapping.fingerprint_sha256 != fingerprint:
            raise LegacyUserPolicyIntegrityError(
                "legacy user-policy revision conflicts with its stored fingerprint"
            )
        return LegacyUserPolicyMappingAction.REPLAY, association
    if source_revision != mapping.last_applied_source_revision + 1:
        raise LegacyUserPolicyIntegrityError(
            "legacy user-policy revision has an unapplied predecessor"
        )
    return LegacyUserPolicyMappingAction.UPDATE, association


def require_mirrored_policy_id(projection: UserPolicyCreationInput) -> UUID:
    """Return the projection's v2 policy, which the Stage 10 mirror always sets.

    Raise LegacyUserPolicyIntegrityError when it is missing.
    """
    if projection.policy_id is None:
        raise LegacyUserPolicyIntegrityError(
            "mirrored saved policy has no v2 policy reference"
        )
    return projection.policy_id
