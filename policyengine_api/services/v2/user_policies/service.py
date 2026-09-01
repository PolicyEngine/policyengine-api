"""Session-owning application service for user-policy associations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import sessionmaker
from sqlmodel import Session

from policyengine_api.data.v2.user_policies.queries import (
    UserPolicyPage,
    UserPolicyRead,
    list_user_policies,
    read_user_policy,
)
from policyengine_api.data.v2.user_policies.persistence import (
    create_user_policy,
    delete_user_policy,
    patch_user_policy,
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


class V2UserPolicyService:
    """Own transaction boundaries for native association operations."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sessions = session_factory

    def create_user_policy(
        self,
        command: UserPolicyCreateCommand,
    ) -> UserPolicyRead:
        with self._sessions.begin() as session:
            return create_user_policy(session, command)

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
            return patch_user_policy(
                session,
                country_id=country_id,
                association_id=association_id,
                command=command,
            )

    def delete_user_policy(
        self,
        *,
        country_id: str,
        association_id: UUID,
    ) -> None:
        with self._sessions.begin() as session:
            delete_user_policy(
                session,
                country_id=country_id,
                association_id=association_id,
            )

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
