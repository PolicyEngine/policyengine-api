"""Session-owning application service for user-policy associations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import sessionmaker
from sqlmodel import Session

from policyengine_api.data.v2.user_policies.creates import (
    create_user_policy as create_user_policy_row,
)
from policyengine_api.data.v2.user_policies.deletes import (
    delete_user_policy as delete_user_policy_row,
)
from policyengine_api.data.v2.user_policies.reads import (
    UserPolicyPage,
    UserPolicyRead,
    association_read,
    get_user_policy_row,
    list_user_policies,
    read_policy_for_association,
    read_user_policy,
    read_user,
)
from policyengine_api.data.v2.user_policies.updates import (
    update_user_policy,
)
from policyengine_api.services.v2.policies.legacy_translation import (
    LegacyPolicySnapshot,
)
from policyengine_api.services.v2.user_policies.commands import (
    UserPolicyCreateCommand,
    UserPolicyPatchCommand,
)
from policyengine_api.services.v2.user_policies.legacy_service import (
    LegacyUserPolicyPersistenceResult,
    persist_legacy_user_policy,
)
from policyengine_api.services.v2.user_policies.legacy_translation import (
    LegacyUserPolicySnapshot,
)


class AssociationPolicyNotFoundError(LookupError):
    """Raised when an association references an unknown policy UUID."""


class AssociationUserNotFoundError(LookupError):
    """Raised when an association references an unknown v2 user UUID."""


class AssociationCountryConflictError(ValueError):
    """Raised when an association and its referenced policy differ by country."""


class V2UserPolicyService:
    """Own transaction boundaries for native association operations."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sessions = session_factory

    def create_user_policy(
        self,
        command: UserPolicyCreateCommand,
    ) -> UserPolicyRead:
        with self._sessions.begin() as session:
            if read_user(session, command.user_id) is None:
                raise AssociationUserNotFoundError(
                    f"user {command.user_id} was not found"
                )
            policy = read_policy_for_association(session, command.policy_id)
            if policy is None:
                raise AssociationPolicyNotFoundError(
                    f"policy {command.policy_id} was not found"
                )
            if policy.country_id != command.country_id:
                raise AssociationCountryConflictError(
                    "Association country_id must match the referenced policy"
                )
            return association_read(create_user_policy_row(session, command))

    def get_user_policy(
        self,
        *,
        country_id: str,
        association_id: UUID,
    ) -> UserPolicyRead:
        with self._sessions() as session:
            return read_user_policy(
                session,
                country_id=country_id,
                association_id=association_id,
            )

    def list_user_policies(
        self,
        *,
        country_id: str,
        user_id: UUID,
        policy_id: UUID | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> UserPolicyPage:
        with self._sessions() as session:
            return list_user_policies(
                session,
                country_id=country_id,
                user_id=user_id,
                policy_id=policy_id,
                offset=offset,
                limit=limit,
            )

    def patch_user_policy(
        self,
        *,
        country_id: str,
        association_id: UUID,
        command: UserPolicyPatchCommand,
    ) -> UserPolicyRead:
        with self._sessions.begin() as session:
            association = get_user_policy_row(
                session,
                country_id=country_id,
                association_id=association_id,
            )
            return association_read(update_user_policy(session, association, command))

    def delete_user_policy(
        self,
        *,
        country_id: str,
        association_id: UUID,
    ) -> None:
        with self._sessions.begin() as session:
            association = get_user_policy_row(
                session,
                country_id=country_id,
                association_id=association_id,
            )
            delete_user_policy_row(session, association)

    def mirror_legacy_user_policy(
        self,
        snapshot: LegacyUserPolicySnapshot,
        reform_snapshot: LegacyPolicySnapshot,
        *,
        source_revision: int,
        changed_fields: frozenset[str],
    ) -> LegacyUserPolicyPersistenceResult:
        """Mirror one committed v1 saved policy in one Supabase transaction."""

        with self._sessions.begin() as session:
            return persist_legacy_user_policy(
                session,
                snapshot,
                reform_snapshot,
                source_revision=source_revision,
                changed_fields=changed_fields,
            )
