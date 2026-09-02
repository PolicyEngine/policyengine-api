"""Router-facing and legacy-mirroring services for v2 policies."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from uuid import UUID

from sqlmodel import Session

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS, POLICYENGINE_VERSION
from policyengine_api.services.v2.policies.database_connectors.creates import (
    create_legacy_policy_mapping,
    create_parameter_values,
    create_policy,
)
from policyengine_api.services.v2.policies.database_connectors.reads import (
    read_legacy_policy_mapping,
    read_model_version,
    read_parameter_values,
    read_parameter_values_with_names,
    read_parameters_by_name,
    read_policy_by_content_identity,
    read_policy_catalog,
    read_policy_row,
    read_policy_rows,
    read_version_parameter_ids,
)
from policyengine_api.services.v2.policies.database_session import PolicyDatabaseSession
from policyengine_api.services.v2.policies.transformations import (
    canonical_policy_document,
    canonicalize_policy,
    policy_page,
    policy_parameter_values_by_policy,
    policy_read,
    stored_policy_creation_input,
    translate_legacy_policy,
)
from policyengine_api.services.v2.policies.types import (
    CanonicalPolicyContent,
    LegacyPolicyPersistenceResult,
    LegacyPolicySnapshot,
    NativePolicyCreation,
    NativePolicyCreationInput,
    PolicyCreationInput,
    PolicyCreationResult,
    PolicyPage,
    PolicyRead,
    ResolvedPolicyCreationInput,
)
from policyengine_api.services.v2.policies.validators import (
    LegacyPolicyMappingIntegrityError,
    PolicyContentHashCollisionError,
    PolicyCreationIntegrityError,
    PolicyNotFoundError,
    validate_policy_catalog,
    verify_legacy_policy_mapping,
)


def resolve_policy_creation_input(
    session: Session,
    policy_input: PolicyCreationInput,
    *,
    policyengine_version: str | None = None,
    running_policyengine_version: str = POLICYENGINE_VERSION,
) -> ResolvedPolicyCreationInput:
    selected = read_policy_catalog(
        session,
        policy_input.country_id,
        policyengine_version=policyengine_version,
        running_policyengine_version=running_policyengine_version,
    )
    requested_parameter_ids = {
        value.parameter_id for value in policy_input.parameter_values
    }
    resolved_parameter_ids = read_version_parameter_ids(
        session,
        model_version_id=selected.model_version.id,
        requested_ids=requested_parameter_ids,
    )
    return validate_policy_catalog(
        policy_input,
        selected=selected,
        resolved_parameter_ids=resolved_parameter_ids,
    )


def create_resolved_policy(
    session: Session,
    policy_input: ResolvedPolicyCreationInput,
    *,
    canonicalizer: Callable[
        [ResolvedPolicyCreationInput], CanonicalPolicyContent
    ] = canonicalize_policy,
) -> PolicyCreationResult:
    content = canonicalizer(policy_input)
    created_policy_id = create_policy(
        session,
        policy_input,
        canonicalization_version=content.version,
        content_hash=content.content_hash,
    )
    if created_policy_id is not None:
        create_parameter_values(
            session,
            policy_id=created_policy_id,
            policy_input=policy_input,
        )
        return PolicyCreationResult(policy_id=created_policy_id, created=True)

    existing = read_policy_by_content_identity(
        session,
        canonicalization_version=content.version,
        content_hash=content.content_hash,
    )
    if existing is None:
        raise PolicyCreationIntegrityError(
            "policy hash conflict did not resolve to a stored policy"
        )
    model_version = read_model_version(session, existing.tax_benefit_model_version_id)
    if model_version is None:
        raise PolicyCreationIntegrityError(
            "stored policy references an absent model version"
        )
    stored_input = stored_policy_creation_input(
        existing,
        model_version,
        read_parameter_values(session, existing.id),
    )
    if canonical_policy_document(stored_input) != content.document:
        raise PolicyContentHashCollisionError(
            "stored policy content differs for the same canonical version and hash"
        )
    return PolicyCreationResult(policy_id=existing.id, created=False)


def read_complete_policy(
    session: Session, *, country_id: str, policy_id: UUID
) -> PolicyRead:
    policy = read_policy_row(session, country_id=country_id, policy_id=policy_id)
    if policy is None:
        raise PolicyNotFoundError(f"policy {policy_id} was not found")
    values = policy_parameter_values_by_policy(
        [policy.id], read_parameter_values_with_names(session, [policy.id])
    )
    return policy_read(policy, values)


def read_policy_page(
    session: Session,
    *,
    country_id: str,
    tax_benefit_model_id: UUID | None,
    offset: int,
    limit: int,
) -> PolicyPage:
    rows = read_policy_rows(
        session,
        country_id=country_id,
        tax_benefit_model_id=tax_benefit_model_id,
        offset=offset,
        limit=limit,
    )
    displayed_rows = rows[:limit]
    policy_ids = [policy.id for policy in displayed_rows]
    values = policy_parameter_values_by_policy(
        policy_ids, read_parameter_values_with_names(session, policy_ids)
    )
    return policy_page(rows, values, offset=offset, limit=limit)


def mirror_legacy_policy_in_session(
    session: Session,
    snapshot: LegacyPolicySnapshot,
    *,
    running_policyengine_version: str = POLICYENGINE_VERSION,
    country_package_versions: Mapping[str, str] = COUNTRY_PACKAGE_VERSIONS,
) -> LegacyPolicyPersistenceResult:
    existing = read_legacy_policy_mapping(
        session,
        country_id=snapshot.country_id,
        legacy_policy_id=snapshot.legacy_policy_id,
        lock=True,
    )
    if existing is not None:
        verify_legacy_policy_mapping(
            existing, source_policy_hash=snapshot.source_policy_hash
        )

    selected = read_policy_catalog(
        session,
        snapshot.country_id,
        running_policyengine_version=running_policyengine_version,
    )
    policy_json = snapshot.policy_json
    assert isinstance(policy_json, dict)
    parameters = read_parameters_by_name(
        session,
        model_version_id=selected.model_version.id,
        names=set(policy_json),
    )
    policy_input = translate_legacy_policy(
        snapshot,
        selected=selected,
        parameters=parameters,
        country_package_versions=country_package_versions,
    )
    policy_result = create_resolved_policy(session, policy_input)
    if existing is not None:
        verify_legacy_policy_mapping(
            existing,
            source_policy_hash=snapshot.source_policy_hash,
            expected_policy_id=policy_result.policy_id,
        )
        return LegacyPolicyPersistenceResult(
            policy_id=existing.policy_id,
            policy_created=False,
            mapping_created=False,
        )

    mapping_id = create_legacy_policy_mapping(
        session,
        country_id=snapshot.country_id,
        legacy_policy_id=snapshot.legacy_policy_id,
        source_policy_hash=snapshot.source_policy_hash,
        policy_id=policy_result.policy_id,
    )
    if mapping_id is not None:
        return LegacyPolicyPersistenceResult(
            policy_id=policy_result.policy_id,
            policy_created=policy_result.created,
            mapping_created=True,
        )
    concurrent = read_legacy_policy_mapping(
        session,
        country_id=snapshot.country_id,
        legacy_policy_id=snapshot.legacy_policy_id,
        lock=False,
    )
    if concurrent is None:
        raise LegacyPolicyMappingIntegrityError(
            "legacy policy mapping conflict did not resolve to a stored row"
        )
    verify_legacy_policy_mapping(
        concurrent,
        source_policy_hash=snapshot.source_policy_hash,
        expected_policy_id=policy_result.policy_id,
    )
    return LegacyPolicyPersistenceResult(
        policy_id=concurrent.policy_id,
        policy_created=False,
        mapping_created=False,
    )


class V2PolicyService:
    """Sequence policy operations while delegating database lifetime management."""

    def __init__(
        self,
        database_session: PolicyDatabaseSession,
        *,
        running_policyengine_version: str = POLICYENGINE_VERSION,
    ) -> None:
        self._database_session = database_session
        self._running_policyengine_version = running_policyengine_version

    def create_policy(
        self, policy_input: NativePolicyCreationInput
    ) -> NativePolicyCreation:
        content = PolicyCreationInput.model_validate(
            policy_input.model_dump(exclude={"policyengine_version"})
        )
        with self._database_session.transaction() as session:
            resolved = resolve_policy_creation_input(
                session,
                content,
                policyengine_version=policy_input.policyengine_version,
                running_policyengine_version=self._running_policyengine_version,
            )
            persisted = create_resolved_policy(session, resolved)
            item = read_complete_policy(
                session,
                country_id=policy_input.country_id,
                policy_id=persisted.policy_id,
            )
        return NativePolicyCreation(item=item, created=persisted.created)

    def get_policy(self, *, country_id: str, policy_id: UUID) -> PolicyRead:
        with self._database_session.read() as session:
            return read_complete_policy(
                session, country_id=country_id, policy_id=policy_id
            )

    def list_policies(
        self,
        *,
        country_id: str,
        tax_benefit_model_id: UUID | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> PolicyPage:
        with self._database_session.read() as session:
            return read_policy_page(
                session,
                country_id=country_id,
                tax_benefit_model_id=tax_benefit_model_id,
                offset=offset,
                limit=limit,
            )

    def mirror_legacy_policy(
        self, snapshot: LegacyPolicySnapshot
    ) -> LegacyPolicyPersistenceResult:
        with self._database_session.transaction() as session:
            return mirror_legacy_policy_in_session(
                session,
                snapshot,
                running_policyengine_version=self._running_policyengine_version,
            )
