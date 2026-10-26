"""Router-facing and legacy-mirroring services for v2 policies."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from policyengine_api.constants import POLICYENGINE_VERSION
from policyengine_api.data.v2.catalog.catalog_selection import (
    MetadataCatalogNotPublishedError,
)
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
from policyengine_api.services.v2.policies.transformations import (
    canonical_policy_document,
    canonicalize_policy,
    policy_missing_parameters,
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

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

    from sqlmodel import Session

    from policyengine_api.services.v2.policies.database_session import (
        PolicyDatabaseSession,
    )


def resolve_policy_creation_input(
    session: Session,
    policy_input: PolicyCreationInput,
    *,
    policyengine_version: str | None = None,
    running_policyengine_version: str = POLICYENGINE_VERSION,
) -> ResolvedPolicyCreationInput:
    """Bind policy content to the selected catalog's model version.

    Raise PolicyCatalogValidationError if the model or any parameter id is not
    part of the selected catalog.
    """
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
    """Store a resolved policy, or return the existing one with identical content.

    Raise PolicyCreationIntegrityError if the hash conflict finds no usable row,
    and PolicyContentHashCollisionError if the stored row's canonical bytes differ.
    """
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
        msg = "policy hash conflict did not resolve to a stored policy"
        raise PolicyCreationIntegrityError(msg)
    model_version = read_model_version(session, existing.tax_benefit_model_version_id)
    if model_version is None:
        msg = "stored policy references an absent model version"
        raise PolicyCreationIntegrityError(msg)
    stored_input = stored_policy_creation_input(
        existing,
        model_version,
        read_parameter_values(session, existing.id),
    )
    if canonical_policy_document(stored_input) != content.document:
        msg = "stored policy content differs for the same canonical version and hash"
        raise PolicyContentHashCollisionError(msg)
    return PolicyCreationResult(policy_id=existing.id, created=False)


def read_complete_policy(
    session: Session, *, country_id: str, policy_id: UUID
) -> PolicyRead:
    """Return one policy of this country, or raise PolicyNotFoundError."""
    policy = read_policy_row(session, country_id=country_id, policy_id=policy_id)
    if policy is None:
        msg = f"policy {policy_id} was not found"
        raise PolicyNotFoundError(msg)
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
    """Return a page of policies with their values, optionally for one model."""
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


def with_missing_parameters(
    session: Session,
    policies: tuple[PolicyRead, ...],
    *,
    country_id: str,
    running_policyengine_version: str = POLICYENGINE_VERSION,
) -> tuple[PolicyRead, ...]:
    """Return the policies with the parameters each sets that the running catalog lacks.

    Each policy's ``missing_parameters`` is None when the running PolicyEngine.py
    version has no published catalog for the country, since nothing can be
    checked. A catalog that cannot be queried raises, as any other read would.
    """
    try:
        selected = read_policy_catalog(
            session,
            country_id,
            running_policyengine_version=running_policyengine_version,
        )
    except MetadataCatalogNotPublishedError:
        return tuple(replace(policy, missing_parameters=None) for policy in policies)
    running_model_version_id = selected.model_version.id
    names_to_check = {
        value.parameter_name
        for policy in policies
        if policy.tax_benefit_model_version_id != running_model_version_id
        for value in policy.parameter_values
    }
    running_parameters = read_parameters_by_name(
        session, model_version_id=running_model_version_id, names=names_to_check
    )
    return tuple(
        replace(
            policy,
            missing_parameters=policy_missing_parameters(
                policy,
                running_model_version_id=running_model_version_id,
                running_parameter_names=running_parameters,
            ),
        )
        for policy in policies
    )


def mirror_legacy_policy_in_session(
    session: Session,
    snapshot: LegacyPolicySnapshot,
    *,
    running_policyengine_version: str = POLICYENGINE_VERSION,
) -> LegacyPolicyPersistenceResult:
    """Copy one committed v1 policy into v2 and map its v1 id to the result.

    The policy is translated against the running catalog, whichever country
    package version it was saved under. A v1 policy that already has a v2 copy
    returns that copy without being translated again, so writing it again after
    a PolicyEngine.py or country package upgrade still succeeds. Raise
    LegacyPolicyMappingIntegrityError if the v1 id is already mapped with a
    different source hash.
    """
    existing = read_legacy_policy_mapping(
        session,
        country_id=snapshot.country_id,
        legacy_policy_id=snapshot.legacy_policy_id,
        lock=True,
    )
    if existing is not None:
        # v1 policies never change, so the same source hash means the mapped
        # v2 policy is still the copy, whichever catalog is running now.
        verify_legacy_policy_mapping(
            existing, source_policy_hash=snapshot.source_policy_hash
        )
        return LegacyPolicyPersistenceResult(
            policy_id=existing.policy_id,
            policy_created=False,
            mapping_created=False,
        )

    selected = read_policy_catalog(
        session,
        snapshot.country_id,
        running_policyengine_version=running_policyengine_version,
    )
    policy_json = snapshot.policy_json
    if not isinstance(policy_json, dict):
        msg = "legacy policy_json must be an object"
        raise TypeError(msg)
    parameters = read_parameters_by_name(
        session,
        model_version_id=selected.model_version.id,
        names=set(policy_json),
    )
    policy_input = translate_legacy_policy(
        snapshot,
        selected=selected,
        parameters=parameters,
    )
    policy_result = create_resolved_policy(session, policy_input)
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
        msg = "legacy policy mapping conflict did not resolve to a stored row"
        raise LegacyPolicyMappingIntegrityError(msg)
    # A concurrent copy mapped the policy first. As with a mapping found at the
    # start, the same source hash makes its v2 policy the copy, even when it was
    # translated with another catalog version than this one. If this copy's
    # translation differed, the v2 policy it inserted commits without a mapping,
    # and the result's policy_created is false because it reports the mapped
    # policy, not that one.
    verify_legacy_policy_mapping(
        concurrent, source_policy_hash=snapshot.source_policy_hash
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
        """Open sessions through ``database_session``.

        ``running_policyengine_version`` selects the catalog when a request names none.
        """
        self._database_session = database_session
        self._running_policyengine_version = running_policyengine_version

    def create_policy(
        self, policy_input: NativePolicyCreationInput
    ) -> NativePolicyCreation:
        """Store native policy content, deduplicated by content hash.

        Return the stored policy and whether this call created it.
        """
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
            (checked,) = with_missing_parameters(
                session,
                (item,),
                country_id=policy_input.country_id,
                running_policyengine_version=self._running_policyengine_version,
            )
        return NativePolicyCreation(item=checked, created=persisted.created)

    def get_policy(self, *, country_id: str, policy_id: UUID) -> PolicyRead:
        """Return one policy of this country, or raise PolicyNotFoundError.

        Its ``missing_parameters`` are checked against the running catalog.
        """
        with self._database_session.read() as session:
            item = read_complete_policy(
                session, country_id=country_id, policy_id=policy_id
            )
            (checked,) = with_missing_parameters(
                session,
                (item,),
                country_id=country_id,
                running_policyengine_version=self._running_policyengine_version,
            )
        return checked

    def list_policies(
        self,
        *,
        country_id: str,
        tax_benefit_model_id: UUID | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> PolicyPage:
        """Return a page of policies, optionally for one tax-benefit model.

        Each policy's ``missing_parameters`` are checked against the running
        catalog.
        """
        with self._database_session.read() as session:
            page = read_policy_page(
                session,
                country_id=country_id,
                tax_benefit_model_id=tax_benefit_model_id,
                offset=offset,
                limit=limit,
            )
            items = with_missing_parameters(
                session,
                page.items,
                country_id=country_id,
                running_policyengine_version=self._running_policyengine_version,
            )
        return replace(page, items=items)

    def mirror_legacy_policy(
        self, snapshot: LegacyPolicySnapshot
    ) -> LegacyPolicyPersistenceResult:
        """Copy one committed v1 policy into v2 in its own transaction."""
        with self._database_session.transaction() as session:
            return mirror_legacy_policy_in_session(
                session,
                snapshot,
                running_policyengine_version=self._running_policyengine_version,
            )
