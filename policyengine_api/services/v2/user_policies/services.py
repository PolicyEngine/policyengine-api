"""Router-facing and legacy-mirroring services for v2 user-policy resources."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.associations.services import (
    require_legacy_reference,
)
from policyengine_api.services.v2.associations.validators import (
    require_not_mirror_owned,
)
from policyengine_api.services.v2.identity.services import (
    resolve_principal_user_for_read_in_session,
    resolve_principal_user_in_session,
)
from policyengine_api.services.v2.legacy_refs.types import LegacyRecordKind
from policyengine_api.services.v2.policies.services import (
    mirror_legacy_policy_in_session,
)
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
    read_all_user_policy_rows,
    read_legacy_user_mapping,
    read_legacy_user_policy_mapping,
    read_mapped_user_policy,
    read_mirrored_policy_ids,
    read_owned_user_policy_row,
    read_policy_for_association,
    read_user,
    read_user_policy_mirror_exists,
    read_user_policy_rows,
)
from policyengine_api.services.v2.user_policies.database_connectors.updates import (
    update_legacy_user_policy_state,
    update_user_policy,
)
from policyengine_api.services.v2.user_policies.transformations import (
    USER_POLICY_FINGERPRINT_VERSION,
    fingerprint_legacy_user_policy,
    legacy_name_requires_update,
    owned_user_policy_input,
    project_legacy_user_policy,
    user_policy_page,
    user_policy_read,
)
from policyengine_api.services.v2.user_policies.types import (
    LegacyUserPolicyMappingAction,
    LegacyUserPolicyPersistenceResult,
    LegacyUserPolicySnapshot,
    UserPolicyCreateFields,
    UserPolicyCreationInput,
    UserPolicyPage,
    UserPolicyRead,
    UserPolicyUpdateInput,
)
from policyengine_api.services.v2.user_policies.validators import (
    LegacyUserPolicyIntegrityError,
    require_mirrored_policy_id,
    require_user_policy,
    resolve_association_policy_id,
    validate_association_policy,
    validate_existing_legacy_user_mapping,
    validate_existing_legacy_user_policy_mapping,
    validate_legacy_user_mapping_conflict,
    validate_legacy_user_policy_input,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlmodel import Session

    from policyengine_api.data.v2.models import LegacyUserPolicyMapping, UserPolicy
    from policyengine_api.services.v2.associations.types import LegacyReferenceChecker
    from policyengine_api.services.v2.identity.types import AccountPrincipal
    from policyengine_api.services.v2.policies.types import LegacyPolicySnapshot
    from policyengine_api.services.v2.user_policies.database_session import (
        UserPolicyDatabaseSession,
    )


def read_user_policy_page(
    session: Session,
    *,
    country_id: str,
    user_id: UUID,
    policy_id: UUID | None,
    offset: int,
    limit: int,
    legacy_policy_id: int | None = None,
) -> UserPolicyPage:
    """Return a page of a user's associations, optionally for one policy."""
    rows = read_user_policy_rows(
        session,
        country_id=country_id,
        user_id=user_id,
        policy_id=policy_id,
        legacy_policy_id=legacy_policy_id,
        offset=offset,
        limit=limit,
    )
    return user_policy_page(rows, offset=offset, limit=limit)


def read_owned_user_policy(
    session: Session,
    *,
    user_id: UUID | None,
    country_id: str,
    association_id: UUID,
) -> UserPolicy:
    """``user_id`` is None for an unauthenticated user that owns nothing yet."""
    return require_user_policy(
        None
        if user_id is None
        else read_owned_user_policy_row(
            session,
            user_id=user_id,
            country_id=country_id,
            association_id=association_id,
        ),
        association_id=association_id,
    )


def resolve_user_policy_reference(
    session: Session,
    *,
    country_id: str,
    policy_id: UUID | None,
    legacy_policy_id: int | None,
) -> UUID | None:
    """Validate an explicit v2 policy and combine it with the v1 mapping."""
    if policy_id is not None:
        validate_association_policy(
            country_id=country_id,
            policy_id=policy_id,
            policy=read_policy_for_association(session, policy_id),
        )
    mapped_policy_id = (
        read_mirrored_policy_ids(
            session,
            country_id=country_id,
            legacy_policy_ids=(legacy_policy_id,),
        ).get(legacy_policy_id)
        if legacy_policy_id is not None
        else None
    )
    return resolve_association_policy_id(
        requested_policy_id=policy_id,
        mapped_policy_id=mapped_policy_id,
    )


def read_all_user_policies(
    session: Session, *, user_id: UUID
) -> tuple[UserPolicyRead, ...]:
    """Return every association owned by a user, across countries."""
    return tuple(
        user_policy_read(row)
        for row in read_all_user_policy_rows(session, user_id=user_id)
    )


def resolve_legacy_user_id(
    session: Session,
    *,
    legacy_user_id: str,
    primary_country: str,
) -> UUID:
    """Return the v2 user id for a v1 user id, creating a transition user if needed.

    If a concurrent transaction maps the v1 id first, the new user is deleted and
    the winner's user is returned.
    """
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
    """Apply one v1 revision to an already-mapped association.

    Stale and replayed revisions change nothing. The next revision renames the
    association only if the v1 reform label changed. Raise
    LegacyUserPolicyIntegrityError on conflicting or skipped revisions.
    """
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
    policy_id = require_mirrored_policy_id(projection)
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
            policy_id=policy_id,
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
            policy_id=policy_id,
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
        policy_id=policy_id,
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
    """Copy one revision of a v1 saved policy into v2.

    Copy its reform policy, resolve the v1 user to a v2 user, then create or
    update the association. Only the v1 reform label is copied, as the name.
    """
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
    """Sequence owner-scoped association operations through explicit sessions.

    The owner always comes from the verified session principal: a signed-in
    user or a signed-out browser. Reads never provision a browser's
    unauthenticated user; one that does not exist yet owns no records. v1
    references are checked in a short read-only v1 transaction before the v2
    transaction opens.
    """

    def __init__(
        self,
        database_session: UserPolicyDatabaseSession,
        legacy_references: LegacyReferenceChecker | None = None,
    ) -> None:
        self._database_session = database_session
        self._legacy_references = legacy_references

    def _require_legacy_policy(self, *, country_id: str, legacy_policy_id: int) -> None:
        require_legacy_reference(
            self._legacy_references,
            LegacyRecordKind.POLICY,
            country_id=country_id,
            legacy_id=legacy_policy_id,
        )

    def create_user_policy(
        self,
        *,
        principal: AccountPrincipal,
        association_input: UserPolicyCreateFields,
    ) -> UserPolicyRead:
        if association_input.legacy_policy_id is not None:
            self._require_legacy_policy(
                country_id=association_input.country_id,
                legacy_policy_id=association_input.legacy_policy_id,
            )
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_in_session(
                session,
                principal,
                country_id=association_input.country_id,
            )
            policy_id = resolve_user_policy_reference(
                session,
                country_id=association_input.country_id,
                policy_id=association_input.policy_id,
                legacy_policy_id=association_input.legacy_policy_id,
            )
            return user_policy_read(
                create_user_policy(
                    session,
                    owned_user_policy_input(
                        association_input,
                        user_id=owner.user_id,
                        policy_id=policy_id,
                    ),
                )
            )

    def get_user_policy(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        association_id: UUID,
    ) -> UserPolicyRead:
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_for_read_in_session(
                session, principal, country_id=country_id
            )
            return user_policy_read(
                read_owned_user_policy(
                    session,
                    user_id=None if owner is None else owner.user_id,
                    country_id=country_id,
                    association_id=association_id,
                )
            )

    def list_user_policies(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        policy_id: UUID | None = None,
        legacy_policy_id: int | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> UserPolicyPage:
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_for_read_in_session(
                session, principal, country_id=country_id
            )
            if owner is None:
                return user_policy_page([], offset=offset, limit=limit)
            return read_user_policy_page(
                session,
                country_id=country_id,
                user_id=owner.user_id,
                policy_id=policy_id,
                legacy_policy_id=legacy_policy_id,
                offset=offset,
                limit=limit,
            )

    def patch_user_policy(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        association_id: UUID,
        association_input: UserPolicyUpdateInput,
    ) -> UserPolicyRead:
        repoint = "legacy_policy_id" in association_input.model_fields_set
        if repoint:
            assert association_input.legacy_policy_id is not None
            self._require_legacy_policy(
                country_id=country_id,
                legacy_policy_id=association_input.legacy_policy_id,
            )
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_in_session(
                session, principal, country_id=country_id
            )
            association = read_owned_user_policy(
                session,
                user_id=owner.user_id,
                country_id=country_id,
                association_id=association_id,
            )
            require_not_mirror_owned(
                read_user_policy_mirror_exists(session, association_id=association.id),
                association_id=association.id,
            )
            repointed_policy_id = (
                read_mirrored_policy_ids(
                    session,
                    country_id=country_id,
                    legacy_policy_ids=(association_input.legacy_policy_id,),
                ).get(association_input.legacy_policy_id)
                if repoint and association_input.legacy_policy_id is not None
                else None
            )
            return user_policy_read(
                update_user_policy(
                    session,
                    association,
                    association_input,
                    repointed_policy_id=repointed_policy_id,
                    repoint=repoint,
                )
            )

    def delete_user_policy(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        association_id: UUID,
    ) -> None:
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_in_session(
                session, principal, country_id=country_id
            )
            association = read_owned_user_policy(
                session,
                user_id=owner.user_id,
                country_id=country_id,
                association_id=association_id,
            )
            require_not_mirror_owned(
                read_user_policy_mirror_exists(session, association_id=association.id),
                association_id=association.id,
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
        """Copy one v1 saved-policy revision into v2 in its own transaction."""
        with self._database_session.transaction() as session:
            return mirror_legacy_user_policy_in_session(
                session,
                snapshot,
                reform_snapshot,
                source_revision=source_revision,
                changed_fields=changed_fields,
            )
