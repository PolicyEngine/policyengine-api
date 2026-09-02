"""Router-facing and legacy-mirroring services for v2 user-policy resources."""

from __future__ import annotations

from uuid import UUID

from sqlmodel import Session

from policyengine_api.data.v2.models import LegacyUserPolicyMapping
from policyengine_api.services.v2.policies.services import (
    mirror_legacy_policy_in_session,
)
from policyengine_api.services.v2.policies.types import LegacyPolicySnapshot
from policyengine_api.services.v2.user_policies.database_connectors.creates import (
    create_legacy_user_mapping,
    create_legacy_user_policy_mapping,
    create_transition_user,
    create_user_policy,
)
from policyengine_api.services.v2.user_policies.database_connectors.deletes import (
    delete_transition_user,
    delete_user_policy,
)
from policyengine_api.services.v2.user_policies.database_connectors.reads import (
    read_legacy_user_mapping,
    read_legacy_user_policy_mapping,
    read_mapped_user_policy,
    read_policy_for_association,
    read_user,
    read_user_policy_row,
    read_user_policy_rows,
)
from policyengine_api.services.v2.user_policies.database_connectors.updates import (
    update_legacy_user_policy_state,
    update_user_policy,
)
from policyengine_api.services.v2.user_policies.database_session import (
    UserPolicyDatabaseSession,
)
from policyengine_api.services.v2.user_policies.transformations import (
    USER_POLICY_FINGERPRINT_VERSION,
    fingerprint_legacy_user_policy,
    legacy_name_requires_update,
    project_legacy_user_policy,
    user_policy_page,
    user_policy_read,
)
from policyengine_api.services.v2.user_policies.types import (
    LegacyUserPolicyMappingAction,
    LegacyUserPolicyPersistenceResult,
    LegacyUserPolicySnapshot,
    UserPolicyCreationInput,
    UserPolicyPage,
    UserPolicyRead,
    UserPolicyUpdateInput,
)
from policyengine_api.services.v2.user_policies.validators import (
    LegacyUserPolicyIntegrityError,
    require_user_policy,
    validate_association_creation,
    validate_existing_legacy_user_mapping,
    validate_existing_legacy_user_policy_mapping,
    validate_legacy_user_mapping_conflict,
    validate_legacy_user_policy_input,
)


def read_complete_user_policy(
    session: Session, *, country_id: str, association_id: UUID
) -> UserPolicyRead:
    association = require_user_policy(
        read_user_policy_row(
            session,
            country_id=country_id,
            association_id=association_id,
        ),
        association_id=association_id,
    )
    return user_policy_read(association)


def read_user_policy_page(
    session: Session,
    *,
    country_id: str,
    user_id: UUID,
    policy_id: UUID | None,
    offset: int,
    limit: int,
) -> UserPolicyPage:
    rows = read_user_policy_rows(
        session,
        country_id=country_id,
        user_id=user_id,
        policy_id=policy_id,
        offset=offset,
        limit=limit,
    )
    return user_policy_page(rows, offset=offset, limit=limit)


def resolve_legacy_user_id(
    session: Session,
    *,
    legacy_user_id: str,
    primary_country: str,
) -> UUID:
    existing = read_legacy_user_mapping(session, legacy_user_id, lock=True)
    if existing is not None:
        return validate_existing_legacy_user_mapping(
            existing,
            user=read_user(session, existing.user_id),
        )

    user = create_transition_user(session, primary_country=primary_country)
    created_user_id = create_legacy_user_mapping(
        session,
        legacy_user_id=legacy_user_id,
        user_id=user.id,
    )
    if created_user_id is not None:
        return created_user_id

    delete_transition_user(session, user)
    concurrent = read_legacy_user_mapping(session, legacy_user_id, lock=False)
    return validate_legacy_user_mapping_conflict(
        concurrent,
        user=(
            read_user(session, concurrent.user_id) if concurrent is not None else None
        ),
    )


def apply_existing_legacy_user_policy_mapping(
    session: Session,
    *,
    mapping: LegacyUserPolicyMapping,
    country_id: str,
    reform_label: str | None,
    fingerprint: str,
    user_id: UUID,
    policy_id: UUID,
    changed_fields: frozenset[str],
    source_revision: int,
) -> LegacyUserPolicyPersistenceResult:
    action, association = validate_existing_legacy_user_policy_mapping(
        mapping,
        association=read_mapped_user_policy(session, mapping),
        country_id=country_id,
        fingerprint=fingerprint,
        user_id=user_id,
        policy_id=policy_id,
        source_revision=source_revision,
        fingerprint_version=USER_POLICY_FINGERPRINT_VERSION,
    )
    if action in {
        LegacyUserPolicyMappingAction.STALE,
        LegacyUserPolicyMappingAction.REPLAY,
    }:
        return LegacyUserPolicyPersistenceResult(
            association_id=association.id,
            policy_id=policy_id,
            association_created=False,
            association_updated=False,
            mapping_created=False,
        )

    association_updated = legacy_name_requires_update(
        association,
        reform_label=reform_label,
        changed_fields=changed_fields,
    )
    update_legacy_user_policy_state(
        session,
        association=association,
        mapping=mapping,
        reform_label=reform_label,
        update_name=association_updated,
        fingerprint=fingerprint,
        source_revision=source_revision,
    )
    return LegacyUserPolicyPersistenceResult(
        association_id=association.id,
        policy_id=policy_id,
        association_created=False,
        association_updated=association_updated,
        mapping_created=False,
    )


def persist_legacy_user_policy_mapping(
    session: Session,
    *,
    country_id: str,
    legacy_user_policy_id: int,
    reform_label: str | None,
    projection: UserPolicyCreationInput,
    fingerprint: str,
    source_revision: int,
    changed_fields: frozenset[str],
) -> LegacyUserPolicyPersistenceResult:
    existing = read_legacy_user_policy_mapping(
        session,
        country_id=country_id,
        legacy_user_policy_id=legacy_user_policy_id,
        lock=True,
    )
    if existing is not None:
        return apply_existing_legacy_user_policy_mapping(
            session,
            mapping=existing,
            country_id=country_id,
            reform_label=reform_label,
            fingerprint=fingerprint,
            user_id=projection.user_id,
            policy_id=projection.policy_id,
            changed_fields=changed_fields,
            source_revision=source_revision,
        )

    association = create_user_policy(session, projection)
    mapping_id = create_legacy_user_policy_mapping(
        session,
        country_id=country_id,
        legacy_user_policy_id=legacy_user_policy_id,
        user_policy_id=association.id,
        source_revision=source_revision,
        fingerprint_version=USER_POLICY_FINGERPRINT_VERSION,
        fingerprint=fingerprint,
    )
    if mapping_id is not None:
        return LegacyUserPolicyPersistenceResult(
            association_id=association.id,
            policy_id=projection.policy_id,
            association_created=True,
            association_updated=False,
            mapping_created=True,
        )

    delete_user_policy(session, association)
    concurrent = read_legacy_user_policy_mapping(
        session,
        country_id=country_id,
        legacy_user_policy_id=legacy_user_policy_id,
        lock=False,
    )
    if concurrent is None:
        raise LegacyUserPolicyIntegrityError(
            "legacy user-policy mapping conflict did not resolve to a stored row"
        )
    return apply_existing_legacy_user_policy_mapping(
        session,
        mapping=concurrent,
        country_id=country_id,
        reform_label=reform_label,
        fingerprint=fingerprint,
        user_id=projection.user_id,
        policy_id=projection.policy_id,
        changed_fields=changed_fields,
        source_revision=source_revision,
    )


def mirror_legacy_user_policy_in_session(
    session: Session,
    snapshot: LegacyUserPolicySnapshot,
    reform_snapshot: LegacyPolicySnapshot,
    *,
    source_revision: int,
    changed_fields: frozenset[str] = frozenset(),
) -> LegacyUserPolicyPersistenceResult:
    validate_legacy_user_policy_input(
        snapshot,
        reform_snapshot,
        source_revision=source_revision,
    )
    policy_result = mirror_legacy_policy_in_session(session, reform_snapshot)
    user_id = resolve_legacy_user_id(
        session,
        legacy_user_id=snapshot.user_id,
        primary_country=snapshot.country_id,
    )
    projection = project_legacy_user_policy(
        snapshot,
        user_id=user_id,
        policy_id=policy_result.policy_id,
    )
    return persist_legacy_user_policy_mapping(
        session,
        country_id=snapshot.country_id,
        legacy_user_policy_id=snapshot.legacy_user_policy_id,
        reform_label=snapshot.reform_label,
        projection=projection,
        fingerprint=fingerprint_legacy_user_policy(snapshot),
        source_revision=source_revision,
        changed_fields=changed_fields,
    )


class V2UserPolicyService:
    """Sequence association operations through explicit database sessions."""

    def __init__(self, database_session: UserPolicyDatabaseSession) -> None:
        self._database_session = database_session

    def create_user_policy(
        self, association_input: UserPolicyCreationInput
    ) -> UserPolicyRead:
        with self._database_session.transaction() as session:
            policy = read_policy_for_association(session, association_input.policy_id)
            validate_association_creation(
                association_input,
                user=read_user(session, association_input.user_id),
                policy=policy,
            )
            return user_policy_read(create_user_policy(session, association_input))

    def get_user_policy(
        self, *, country_id: str, association_id: UUID
    ) -> UserPolicyRead:
        with self._database_session.read() as session:
            return read_complete_user_policy(
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
        with self._database_session.read() as session:
            return read_user_policy_page(
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
        association_input: UserPolicyUpdateInput,
    ) -> UserPolicyRead:
        with self._database_session.transaction() as session:
            association = require_user_policy(
                read_user_policy_row(
                    session,
                    country_id=country_id,
                    association_id=association_id,
                ),
                association_id=association_id,
            )
            return user_policy_read(
                update_user_policy(session, association, association_input)
            )

    def delete_user_policy(self, *, country_id: str, association_id: UUID) -> None:
        with self._database_session.transaction() as session:
            association = require_user_policy(
                read_user_policy_row(
                    session,
                    country_id=country_id,
                    association_id=association_id,
                ),
                association_id=association_id,
            )
            delete_user_policy(session, association)

    def mirror_legacy_user_policy(
        self,
        snapshot: LegacyUserPolicySnapshot,
        reform_snapshot: LegacyPolicySnapshot,
        *,
        source_revision: int,
        changed_fields: frozenset[str],
    ) -> LegacyUserPolicyPersistenceResult:
        with self._database_session.transaction() as session:
            return mirror_legacy_user_policy_in_session(
                session,
                snapshot,
                reform_snapshot,
                source_revision=source_revision,
                changed_fields=changed_fields,
            )
