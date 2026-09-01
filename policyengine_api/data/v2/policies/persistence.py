"""Conflict-aware PostgreSQL persistence for immutable v2 policies."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, col, select

from policyengine_api.data.v2.models import (
    ParameterValue,
    Policy,
    TaxBenefitModelVersion,
)
from policyengine_api.data.v2.policies.canonicalization import (
    CanonicalPolicyContent,
    canonical_policy_document,
    canonicalize_policy,
)
from policyengine_api.data.v2.policies.schemas import ResolvedPolicyCreateCommand


class PolicyPersistenceIntegrityError(RuntimeError):
    """Raised when policy hash persistence no longer matches stored content."""


class PolicyContentHashCollisionError(PolicyPersistenceIntegrityError):
    """Raised when equal version/hash keys identify different canonical bytes."""


@dataclass(frozen=True)
class PolicyPersistenceResult:
    """Inserted or deduplicated immutable policy identity."""

    policy_id: UUID
    created: bool


def _insert_policy(
    session: Session,
    command: ResolvedPolicyCreateCommand,
    content: CanonicalPolicyContent,
) -> UUID | None:
    policy_id = uuid4()
    statement = (
        insert(Policy)
        .values(
            id=policy_id,
            country_id=command.country_id,
            tax_benefit_model_id=command.tax_benefit_model_id,
            tax_benefit_model_version_id=command.tax_benefit_model_version_id,
            canonicalization_version=content.version,
            content_hash=content.content_hash,
        )
        .on_conflict_do_nothing(constraint="uq_policies_canonicalization_content_hash")
        .returning(col(Policy.id))
    )
    return session.execute(statement).scalar_one_or_none()


def _insert_parameter_values(
    session: Session,
    *,
    policy_id: UUID,
    command: ResolvedPolicyCreateCommand,
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
            for value in command.parameter_values
        ]
    )
    session.flush()


def _stored_policy_command(
    session: Session,
    policy: Policy,
) -> ResolvedPolicyCreateCommand:
    model_version = session.get(
        TaxBenefitModelVersion,
        policy.tax_benefit_model_version_id,
    )
    if model_version is None:
        raise PolicyPersistenceIntegrityError(
            "stored policy references an absent model version"
        )
    values = session.exec(
        select(ParameterValue).where(ParameterValue.policy_id == policy.id)
    ).all()
    return ResolvedPolicyCreateCommand.model_validate(
        {
            "country_id": policy.country_id,
            "tax_benefit_model_id": policy.tax_benefit_model_id,
            "tax_benefit_model_version_id": policy.tax_benefit_model_version_id,
            "policyengine_version": model_version.version,
            "parameter_values": [
                {
                    "parameter_id": value.parameter_id,
                    "value": value.value_json,
                    "start_date": value.start_date,
                    "end_date": value.end_date,
                }
                for value in values
            ],
        }
    )


def _existing_policy_after_conflict(
    session: Session,
    content: CanonicalPolicyContent,
) -> Policy:
    policy = session.exec(
        select(Policy).where(
            Policy.canonicalization_version == content.version,
            Policy.content_hash == content.content_hash,
        )
    ).one_or_none()
    if policy is None:
        raise PolicyPersistenceIntegrityError(
            "policy hash conflict did not resolve to a stored policy"
        )
    return policy


def persist_resolved_policy(
    session: Session,
    command: ResolvedPolicyCreateCommand,
    *,
    canonicalizer: Callable[
        [ResolvedPolicyCreateCommand], CanonicalPolicyContent
    ] = canonicalize_policy,
) -> PolicyPersistenceResult:
    """Insert one policy atomically or verify and return equivalent content."""

    content = canonicalizer(command)
    inserted_id = _insert_policy(session, command, content)
    if inserted_id is not None:
        _insert_parameter_values(session, policy_id=inserted_id, command=command)
        return PolicyPersistenceResult(policy_id=inserted_id, created=True)

    existing = _existing_policy_after_conflict(session, content)
    stored_document = canonical_policy_document(
        _stored_policy_command(session, existing)
    )
    if stored_document != content.document:
        raise PolicyContentHashCollisionError(
            "stored policy content differs for the same canonical version and hash"
        )
    return PolicyPersistenceResult(policy_id=existing.id, created=False)
