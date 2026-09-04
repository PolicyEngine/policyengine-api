"""Database selections used by immutable v2 policy operations."""

from __future__ import annotations

from uuid import UUID

from sqlmodel import Session, col, select

from policyengine_api.constants import POLICYENGINE_VERSION
from policyengine_api.data.v2.catalog.catalog_selection import (
    SelectedCatalog,
    select_catalog,
)
from policyengine_api.data.v2.models import (
    LegacyPolicyMapping,
    Parameter,
    ParameterValue,
    Policy,
    TaxBenefitModelVersion,
)


def read_policy_catalog(
    session: Session,
    country_id: str,
    *,
    policyengine_version: str | None = None,
    running_policyengine_version: str = POLICYENGINE_VERSION,
) -> SelectedCatalog:
    return select_catalog(
        session,
        country_id=country_id,
        running_policyengine_version=running_policyengine_version,
        policyengine_version=policyengine_version,
    )


def read_version_parameter_ids(
    session: Session, *, model_version_id: UUID, requested_ids: set[UUID]
) -> set[UUID]:
    if not requested_ids:
        return set()
    return set(
        session.exec(
            select(Parameter.id).where(
                Parameter.tax_benefit_model_version_id == model_version_id,
                col(Parameter.id).in_(requested_ids),
            )
        ).all()
    )


def read_parameters_by_name(
    session: Session, *, model_version_id: UUID, names: set[str]
) -> dict[str, Parameter]:
    if not names:
        return {}
    parameters = session.exec(
        select(Parameter).where(
            Parameter.tax_benefit_model_version_id == model_version_id,
            col(Parameter.name).in_(names),
        )
    ).all()
    return {parameter.name: parameter for parameter in parameters}


def read_policy_by_content_identity(
    session: Session, *, canonicalization_version: int, content_hash: str
) -> Policy | None:
    return session.exec(
        select(Policy).where(
            Policy.canonicalization_version == canonicalization_version,
            Policy.content_hash == content_hash,
        )
    ).one_or_none()


def read_model_version(
    session: Session, model_version_id: UUID
) -> TaxBenefitModelVersion | None:
    return session.get(TaxBenefitModelVersion, model_version_id)


def read_parameter_values(session: Session, policy_id: UUID) -> list[ParameterValue]:
    return list(
        session.exec(
            select(ParameterValue).where(ParameterValue.policy_id == policy_id)
        ).all()
    )


def read_legacy_policy_mapping(
    session: Session, *, country_id: str, legacy_policy_id: int, lock: bool
) -> LegacyPolicyMapping | None:
    statement = select(LegacyPolicyMapping).where(
        LegacyPolicyMapping.country_id == country_id,
        LegacyPolicyMapping.legacy_policy_id == legacy_policy_id,
    )
    if lock:
        statement = statement.with_for_update()
    return session.exec(statement).one_or_none()


def read_policy_row(
    session: Session, *, country_id: str, policy_id: UUID
) -> Policy | None:
    return session.exec(
        select(Policy).where(Policy.id == policy_id, Policy.country_id == country_id)
    ).one_or_none()


def read_policy_rows(
    session: Session,
    *,
    country_id: str,
    tax_benefit_model_id: UUID | None,
    offset: int,
    limit: int,
) -> list[Policy]:
    statement = select(Policy).where(Policy.country_id == country_id)
    if tax_benefit_model_id is not None:
        statement = statement.where(Policy.tax_benefit_model_id == tax_benefit_model_id)
    return list(
        session.exec(
            statement.order_by(col(Policy.created_at), col(Policy.id))
            .offset(offset)
            .limit(limit + 1)
        ).all()
    )


def read_parameter_values_with_names(
    session: Session, policy_ids: list[UUID]
) -> list[tuple[ParameterValue, str]]:
    if not policy_ids:
        return []
    return list(
        session.exec(
            select(ParameterValue, Parameter.name)
            .join(Parameter, col(Parameter.id) == col(ParameterValue.parameter_id))
            .where(col(ParameterValue.policy_id).in_(policy_ids))
            .order_by(
                col(Parameter.name),
                col(ParameterValue.start_date),
                col(ParameterValue.id),
            )
        ).all()
    )
