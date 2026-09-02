"""Session-owning application service for native and mirrored v2 policies."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import sessionmaker
from sqlmodel import Session

from policyengine_api.constants import POLICYENGINE_VERSION
from policyengine_api.data.v2.policies.reads import (
    PolicyPage,
    PolicyRead,
    list_policies,
    read_policy,
)
from policyengine_api.services.v2.policies.commands import (
    NativePolicyCreateCommand,
    PolicyCreateCommand,
)
from policyengine_api.services.v2.policies.creation import (
    create_resolved_policy,
    resolve_policy_catalog,
)
from policyengine_api.services.v2.policies.legacy_service import (
    LegacyPolicyPersistenceResult,
    persist_legacy_policy,
)
from policyengine_api.services.v2.policies.legacy_translation import (
    LegacyPolicySnapshot,
)


@dataclass(frozen=True)
class NativePolicyCreation:
    """Complete policy read plus whether this request inserted it."""

    item: PolicyRead
    created: bool


class V2PolicyService:
    """Own transaction boundaries for immutable policy operations."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        running_policyengine_version: str = POLICYENGINE_VERSION,
    ) -> None:
        self._sessions = session_factory
        self._running_policyengine_version = running_policyengine_version

    def create_policy(
        self,
        command: NativePolicyCreateCommand,
    ) -> NativePolicyCreation:
        content = PolicyCreateCommand.model_validate(
            command.model_dump(exclude={"policyengine_version"})
        )
        with self._sessions.begin() as session:
            resolved = resolve_policy_catalog(
                session,
                content,
                policyengine_version=command.policyengine_version,
                running_policyengine_version=self._running_policyengine_version,
            )
            persisted = create_resolved_policy(session, resolved)
            item = read_policy(
                session,
                country_id=command.country_id,
                policy_id=persisted.policy_id,
            )
        return NativePolicyCreation(item=item, created=persisted.created)

    def get_policy(self, *, country_id: str, policy_id: UUID) -> PolicyRead:
        with self._sessions() as session:
            return read_policy(
                session,
                country_id=country_id,
                policy_id=policy_id,
            )

    def list_policies(
        self,
        *,
        country_id: str,
        tax_benefit_model_id: UUID | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> PolicyPage:
        with self._sessions() as session:
            return list_policies(
                session,
                country_id=country_id,
                tax_benefit_model_id=tax_benefit_model_id,
                offset=offset,
                limit=limit,
            )

    def mirror_legacy_policy(
        self,
        snapshot: LegacyPolicySnapshot,
    ) -> LegacyPolicyPersistenceResult:
        """Mirror one committed v1 row in one Supabase transaction."""

        with self._sessions.begin() as session:
            return persist_legacy_policy(
                session,
                snapshot,
                running_policyengine_version=self._running_policyengine_version,
            )
