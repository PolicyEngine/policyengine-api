"""SQL operations for durable v1-policy-to-v2-policy mappings."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, col, select

from policyengine_api.data.v2.models import LegacyPolicyMapping


class LegacyPolicyMappingIntegrityError(RuntimeError):
    """Raised when one immutable v1 identity maps inconsistently."""


def find_legacy_policy_mapping(
    session: Session,
    *,
    country_id: str,
    legacy_policy_id: int,
    lock: bool,
) -> LegacyPolicyMapping | None:
    statement = select(LegacyPolicyMapping).where(
        LegacyPolicyMapping.country_id == country_id,
        LegacyPolicyMapping.legacy_policy_id == legacy_policy_id,
    )
    if lock:
        statement = statement.with_for_update()
    return session.exec(statement).one_or_none()


def verify_legacy_policy_mapping(
    mapping: LegacyPolicyMapping,
    *,
    source_policy_hash: str,
    expected_policy_id: UUID | None = None,
) -> None:
    if mapping.source_policy_hash != source_policy_hash:
        raise LegacyPolicyMappingIntegrityError(
            "legacy policy identity was presented with a different source hash"
        )
    if expected_policy_id is not None and mapping.policy_id != expected_policy_id:
        raise LegacyPolicyMappingIntegrityError(
            "legacy policy mapping does not match translated immutable content"
        )


def insert_legacy_policy_mapping(
    session: Session,
    *,
    country_id: str,
    legacy_policy_id: int,
    source_policy_hash: str,
    policy_id: UUID,
) -> UUID | None:
    """Insert one mapping and return its UUID, or none after a conflict."""

    return session.execute(
        insert(LegacyPolicyMapping)
        .values(
            country_id=country_id,
            legacy_policy_id=legacy_policy_id,
            policy_id=policy_id,
            source_policy_hash=source_policy_hash,
        )
        .on_conflict_do_nothing(constraint="uq_legacy_policy_mappings_country_legacy")
        .returning(col(LegacyPolicyMapping.id))
    ).scalar_one_or_none()
