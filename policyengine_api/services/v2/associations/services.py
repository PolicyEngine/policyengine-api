"""Operations shared by the four user-owned association services."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlmodel import Session

from policyengine_api.services.v2.associations.database_connectors.creates import (
    import_association,
)
from policyengine_api.services.v2.associations.database_connectors.reads import (
    read_association_ids_by_client_ref,
)
from policyengine_api.services.v2.associations.types import (
    AssociationImport,
    AssociationTable,
    LegacyReferenceChecker,
)
from policyengine_api.services.v2.associations.validators import (
    require_legacy_reference_checker,
    require_unused_client_ref,
)
from policyengine_api.services.v2.legacy_refs.types import LegacyRecordKind


def require_legacy_reference(
    legacy_references: LegacyReferenceChecker | None,
    kind: LegacyRecordKind,
    *,
    country_id: str,
    legacy_id: int,
) -> None:
    """Check one v1 reference before the caller opens its v2 transaction."""

    require_legacy_reference_checker(legacy_references).require_existing(
        country_id=country_id,
        requested={kind: (legacy_id,)},
    )


def require_unused_client_ref_in_session(
    session: Session,
    table: type[AssociationTable],
    *,
    user_id: UUID,
    client_ref: str | None,
) -> None:
    """Reject a single create whose client_ref the owner already uses anywhere."""

    if client_ref is None:
        return
    require_unused_client_ref(
        read_association_ids_by_client_ref(
            session,
            table,
            user_id=user_id,
            client_refs=(client_ref,),
            country_id=None,
        ).get(client_ref),
        client_ref=client_ref,
    )


def import_associations_in_session(
    session: Session,
    table: type[AssociationTable],
    *,
    user_id: UUID,
    country_id: str,
    rows: Sequence[tuple[str, Mapping[str, object]]],
) -> AssociationImport:
    """Insert imported rows idempotently on ``(user_id, client_ref)``.

    An existing client_ref in the import country returns its stored ID
    unchanged. One the owner already uses in another country is reported as a
    conflict instead of being linked across countries.
    """

    ids: dict[str, UUID] = {}
    conflicts: list[str] = []
    for client_ref, values in rows:
        association_id = import_association(
            session, table, values
        ) or read_association_ids_by_client_ref(
            session,
            table,
            user_id=user_id,
            client_refs=(client_ref,),
            country_id=country_id,
        ).get(client_ref)
        if association_id is None:
            conflicts.append(client_ref)
        else:
            ids[client_ref] = association_id
    return AssociationImport(ids=ids, conflicting_client_refs=tuple(conflicts))
