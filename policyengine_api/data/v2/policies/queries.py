"""Country-scoped database queries for immutable v2 policies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlmodel import Session, col, select

from policyengine_api.data.v2.models import Parameter, ParameterValue, Policy


class PolicyNotFoundError(LookupError):
    """Raised when a policy UUID is absent from the selected country."""


@dataclass(frozen=True)
class PolicyParameterValueRead:
    id: UUID
    parameter_id: UUID
    parameter_name: str
    value: Any
    start_date: datetime
    end_date: datetime | None


@dataclass(frozen=True)
class PolicyRead:
    id: UUID
    country_id: str
    tax_benefit_model_id: UUID
    tax_benefit_model_version_id: UUID
    created_at: datetime
    updated_at: datetime
    parameter_values: tuple[PolicyParameterValueRead, ...]


@dataclass(frozen=True)
class PolicyPage:
    items: tuple[PolicyRead, ...]
    offset: int
    limit: int
    has_more: bool


def _parameter_values_by_policy(
    session: Session,
    policy_ids: list[UUID],
) -> dict[UUID, tuple[PolicyParameterValueRead, ...]]:
    grouped: dict[UUID, list[PolicyParameterValueRead]] = {
        policy_id: [] for policy_id in policy_ids
    }
    if not policy_ids:
        return {}
    rows = session.exec(
        select(ParameterValue, Parameter.name)
        .join(Parameter, col(Parameter.id) == col(ParameterValue.parameter_id))
        .where(col(ParameterValue.policy_id).in_(policy_ids))
        .order_by(
            col(Parameter.name),
            col(ParameterValue.start_date),
            col(ParameterValue.id),
        )
    ).all()
    for value, parameter_name in rows:
        if value.policy_id is None:
            continue
        grouped[value.policy_id].append(
            PolicyParameterValueRead(
                id=value.id,
                parameter_id=value.parameter_id,
                parameter_name=parameter_name,
                value=value.value_json,
                start_date=value.start_date,
                end_date=value.end_date,
            )
        )
    return {policy_id: tuple(values) for policy_id, values in grouped.items()}


def _policy_read(
    policy: Policy,
    values: dict[UUID, tuple[PolicyParameterValueRead, ...]],
) -> PolicyRead:
    return PolicyRead(
        id=policy.id,
        country_id=policy.country_id,
        tax_benefit_model_id=policy.tax_benefit_model_id,
        tax_benefit_model_version_id=policy.tax_benefit_model_version_id,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
        parameter_values=values.get(policy.id, ()),
    )


def read_policy(
    session: Session,
    *,
    country_id: str,
    policy_id: UUID,
) -> PolicyRead:
    """Read one complete policy only under its stored country."""

    policy = session.exec(
        select(Policy).where(
            Policy.id == policy_id,
            Policy.country_id == country_id,
        )
    ).one_or_none()
    if policy is None:
        raise PolicyNotFoundError(f"policy {policy_id} was not found")
    values = _parameter_values_by_policy(session, [policy.id])
    return _policy_read(policy, values)


def list_policies(
    session: Session,
    *,
    country_id: str,
    tax_benefit_model_id: UUID | None = None,
    offset: int = 0,
    limit: int = 100,
) -> PolicyPage:
    """Read one deterministic bounded page with optional exact model filtering."""

    statement = select(Policy).where(Policy.country_id == country_id)
    if tax_benefit_model_id is not None:
        statement = statement.where(Policy.tax_benefit_model_id == tax_benefit_model_id)
    rows = session.exec(
        statement.order_by(col(Policy.created_at), col(Policy.id))
        .offset(offset)
        .limit(limit + 1)
    ).all()
    has_more = len(rows) > limit
    policies = rows[:limit]
    values = _parameter_values_by_policy(
        session,
        [policy.id for policy in policies],
    )
    return PolicyPage(
        items=tuple(_policy_read(policy, values) for policy in policies),
        offset=offset,
        limit=limit,
        has_more=has_more,
    )
