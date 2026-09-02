"""Database inserts used by immutable v2 policy operations."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, col

from policyengine_api.data.v2.models import LegacyPolicyMapping, ParameterValue, Policy
from policyengine_api.services.v2.policies.types import ResolvedPolicyCreationInput


def create_policy(
    session: Session,
    policy_input: ResolvedPolicyCreationInput,
    *,
    canonicalization_version: int,
    content_hash: str,
) -> UUID | None:
    policy_id = uuid4()
    statement = (
        insert(Policy)
        .values(
            id=policy_id,
            country_id=policy_input.country_id,
            tax_benefit_model_id=policy_input.tax_benefit_model_id,
            tax_benefit_model_version_id=policy_input.tax_benefit_model_version_id,
            canonicalization_version=canonicalization_version,
            content_hash=content_hash,
        )
        .on_conflict_do_nothing(constraint="uq_policies_canonicalization_content_hash")
        .returning(col(Policy.id))
    )
    return session.execute(statement).scalar_one_or_none()


def create_parameter_values(
    session: Session,
    *,
    policy_id: UUID,
    policy_input: ResolvedPolicyCreationInput,
) -> None:
    session.add_all(
        [
            ParameterValue(
                policy_id=policy_id,
                dynamic_id=None,
                parameter_id=value.parameter_id,
                value_json=value.value,
                start_date=value.start_date,
                end_date=value.end_date,
            )
            for value in policy_input.parameter_values
        ]
    )
    session.flush()


def create_legacy_policy_mapping(
    session: Session,
    *,
    country_id: str,
    legacy_policy_id: int,
    source_policy_hash: str,
    policy_id: UUID,
) -> UUID | None:
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
