"""Router-facing services for v2 dynamics, stored as policies are.

A dynamic is bound to a catalog version and deduplicated by the policies'
canonical content hash, with the policies' catalog reads. This module never
imports ``policies.services``: the v1-to-v2 policy copy there creates
dynamics through ``create_resolved_dynamic``.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError

from policyengine_api.constants import POLICYENGINE_VERSION
from policyengine_api.data.v2.catalog.catalog_selection_validation import (
    MetadataCatalogNotPublishedError,
)
from policyengine_api.services.v2.dynamics.database_connectors.creates import (
    create_dynamic,
    create_dynamic_parameter_values,
)
from policyengine_api.services.v2.dynamics.database_connectors.reads import (
    read_dynamic_by_content_identity,
    read_dynamic_parameter_values,
    read_dynamic_parameter_values_with_names,
    read_dynamic_row,
)
from policyengine_api.services.v2.dynamics.transformations import (
    checked_dynamic_read,
    dynamic_creation_input,
    dynamic_parameter_values_by_dynamic,
    dynamic_read,
)
from policyengine_api.services.v2.dynamics.types import (
    CheckedDynamicRead,
    DynamicCreationInput,
    DynamicCreationResult,
    DynamicRead,
    NativeDynamicCreation,
    NativeDynamicCreationInput,
    ResolvedDynamicCreationInput,
)
from policyengine_api.services.v2.dynamics.validators import (
    DynamicContentHashCollisionError,
    DynamicCreationIntegrityError,
    DynamicNotFoundError,
    DynamicStorageError,
    require_dynamic_parameters,
)
from policyengine_api.services.v2.policies.database_connectors.reads import (
    read_model_version,
    read_parameters_by_name,
    read_policy_catalog,
    read_version_parameter_names,
)
from policyengine_api.services.v2.policies.transformations import (
    canonical_policy_document,
    canonicalize_policy,
    policy_missing_parameters,
    stored_policy_creation_input,
)
from policyengine_api.services.v2.policies.validators import validate_policy_catalog

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from uuid import UUID

    from sqlmodel import Session

    from policyengine_api.services.v2.dynamics.database_session import (
        DynamicDatabaseSession,
    )
    from policyengine_api.services.v2.policies.types import (
        CanonicalPolicyContent,
        ResolvedPolicyCreationInput,
    )


@contextmanager
def _storage_failures() -> Iterator[None]:
    """Raise DynamicStorageError for a database read or write that failed."""
    try:
        yield
    except SQLAlchemyError as error:
        msg = "the v2 database could not be read or written for a dynamic"
        raise DynamicStorageError(msg) from error


def resolve_dynamic_creation_input(
    session: Session,
    dynamic_input: DynamicCreationInput,
    *,
    policyengine_version: str | None = None,
    running_policyengine_version: str = POLICYENGINE_VERSION,
) -> ResolvedDynamicCreationInput:
    """Bind dynamic content to the selected catalog's model version.

    Raise PolicyCatalogValidationError if the model or any parameter id is not
    part of the selected catalog, and DynamicSetsPolicyParametersError if any
    parameter is not one of the model's assumptions.
    """
    selected = read_policy_catalog(
        session,
        dynamic_input.country_id,
        policyengine_version=policyengine_version,
        running_policyengine_version=running_policyengine_version,
    )
    parameter_names = read_version_parameter_names(
        session,
        model_version_id=selected.model_version.id,
        requested_ids={value.parameter_id for value in dynamic_input.parameter_values},
    )
    resolved = validate_policy_catalog(
        dynamic_input,
        selected=selected,
        resolved_parameter_ids=set(parameter_names),
    )
    require_dynamic_parameters(dynamic_input.country_id, parameter_names.values())
    return dynamic_creation_input(resolved)


def create_resolved_dynamic(
    session: Session,
    dynamic_input: ResolvedDynamicCreationInput,
    *,
    canonicalizer: Callable[
        [ResolvedPolicyCreationInput], CanonicalPolicyContent
    ] = canonicalize_policy,
) -> DynamicCreationResult:
    """Store a resolved dynamic, or return the existing one with identical content.

    Raise DynamicCreationIntegrityError if the hash conflict finds no usable
    row, and DynamicContentHashCollisionError if the stored row's canonical
    bytes differ.
    """
    content = canonicalizer(dynamic_input)
    created_dynamic_id = create_dynamic(
        session,
        dynamic_input,
        canonicalization_version=content.version,
        content_hash=content.content_hash,
    )
    if created_dynamic_id is not None:
        create_dynamic_parameter_values(
            session, dynamic_id=created_dynamic_id, dynamic_input=dynamic_input
        )
        return DynamicCreationResult(dynamic_id=created_dynamic_id, created=True)

    existing = read_dynamic_by_content_identity(
        session,
        canonicalization_version=content.version,
        content_hash=content.content_hash,
    )
    if existing is None:
        msg = "dynamic hash conflict did not resolve to a stored dynamic"
        raise DynamicCreationIntegrityError(msg)
    model_version = read_model_version(session, existing.tax_benefit_model_version_id)
    if model_version is None:
        msg = "stored dynamic references an absent model version"
        raise DynamicCreationIntegrityError(msg)
    stored_input = stored_policy_creation_input(
        existing,
        model_version,
        read_dynamic_parameter_values(session, existing.id),
    )
    if canonical_policy_document(stored_input) != content.document:
        msg = "stored dynamic content differs for the same canonical version and hash"
        raise DynamicContentHashCollisionError(msg)
    return DynamicCreationResult(dynamic_id=existing.id, created=False)


def read_complete_dynamic(
    session: Session, *, country_id: str, dynamic_id: UUID
) -> DynamicRead:
    """Return one dynamic of this country, or raise DynamicNotFoundError."""
    dynamic = read_dynamic_row(session, country_id=country_id, dynamic_id=dynamic_id)
    if dynamic is None:
        msg = f"dynamic {dynamic_id} was not found"
        raise DynamicNotFoundError(msg)
    values = dynamic_parameter_values_by_dynamic(
        [dynamic.id], read_dynamic_parameter_values_with_names(session, [dynamic.id])
    )
    return dynamic_read(dynamic, values)


def with_missing_dynamic_parameters(
    session: Session,
    dynamic: DynamicRead,
    *,
    country_id: str,
    running_policyengine_version: str = POLICYENGINE_VERSION,
) -> CheckedDynamicRead:
    """Return the dynamic with the parameters it sets that the running catalog lacks.

    As for a policy, ``missing_parameters`` is None when the running
    PolicyEngine.py version has no published catalog for the country. A
    catalog that cannot be queried raises, as any other read would.
    """
    try:
        selected = read_policy_catalog(
            session,
            country_id,
            running_policyengine_version=running_policyengine_version,
        )
    except MetadataCatalogNotPublishedError:
        return checked_dynamic_read(dynamic, None)
    running_model_version_id = selected.model_version.id
    names_to_check = (
        set()
        if dynamic.tax_benefit_model_version_id == running_model_version_id
        else {value.parameter_name for value in dynamic.parameter_values}
    )
    running_parameters = read_parameters_by_name(
        session, model_version_id=running_model_version_id, names=names_to_check
    )
    return checked_dynamic_read(
        dynamic,
        policy_missing_parameters(
            dynamic,
            running_model_version_id=running_model_version_id,
            running_parameter_names=running_parameters,
        ),
    )


class V2DynamicService:
    """Sequence dynamic operations while delegating database lifetime management."""

    def __init__(
        self,
        database_session: DynamicDatabaseSession,
        *,
        running_policyengine_version: str = POLICYENGINE_VERSION,
    ) -> None:
        """Open sessions through ``database_session``.

        ``running_policyengine_version`` selects the catalog when a request names none.
        """
        self._database_session = database_session
        self._running_policyengine_version = running_policyengine_version

    def create_dynamic(
        self, dynamic_input: NativeDynamicCreationInput
    ) -> NativeDynamicCreation:
        """Store native dynamic content, deduplicated by content hash.

        Return the stored dynamic and whether this call created it. Raise
        DynamicStorageError when the database cannot be read or written.
        """
        content = DynamicCreationInput.model_validate(
            dynamic_input.model_dump(exclude={"policyengine_version"})
        )
        with _storage_failures(), self._database_session.transaction() as session:
            resolved = resolve_dynamic_creation_input(
                session,
                content,
                policyengine_version=dynamic_input.policyengine_version,
                running_policyengine_version=self._running_policyengine_version,
            )
            persisted = create_resolved_dynamic(session, resolved)
            item = read_complete_dynamic(
                session,
                country_id=dynamic_input.country_id,
                dynamic_id=persisted.dynamic_id,
            )
            checked = with_missing_dynamic_parameters(
                session,
                item,
                country_id=dynamic_input.country_id,
                running_policyengine_version=self._running_policyengine_version,
            )
        return NativeDynamicCreation(item=checked, created=persisted.created)

    def get_dynamic(self, *, country_id: str, dynamic_id: UUID) -> CheckedDynamicRead:
        """Return one dynamic of this country, or raise DynamicNotFoundError.

        Its ``missing_parameters`` are checked against the running catalog.
        Raise DynamicStorageError when the database cannot be read.
        """
        with _storage_failures(), self._database_session.read() as session:
            item = read_complete_dynamic(
                session, country_id=country_id, dynamic_id=dynamic_id
            )
            return with_missing_dynamic_parameters(
                session,
                item,
                country_id=country_id,
                running_policyengine_version=self._running_policyengine_version,
            )
