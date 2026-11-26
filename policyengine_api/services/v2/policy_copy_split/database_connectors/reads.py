"""Database selections used by the policy copy split."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import and_, func, or_
from sqlmodel import Session, col, select

from policyengine_api.data.v2.models import (
    HouseholdJob,
    LegacyPolicyMapping,
    Parameter,
    ParameterValue,
    Policy,
    Report,
    Simulation,
    UserDynamic,
    UserPolicy,
)
from policyengine_api.services.v2.policy_copy_split.types import CopyReferences

if TYPE_CHECKING:
    from collections.abc import Mapping
    from uuid import UUID

    from policyengine_api.supported_countries import SupportedCountryId


def read_policy_ids_setting_parameters(
    session: Session, prefixes_by_country: Mapping[SupportedCountryId, tuple[str, ...]]
) -> list[UUID]:
    """Return the stored policies that set a parameter under their country's prefixes.

    Oldest first. Only a policy's own values count, not current law's or a
    dynamic's.
    """
    sets_prefixed_parameter = or_(
        *(
            and_(
                col(Policy.country_id) == country_id,
                or_(
                    *(
                        col(Parameter.name).startswith(prefix, autoescape=True)
                        for prefix in prefixes
                    )
                ),
            )
            for country_id, prefixes in prefixes_by_country.items()
        )
    )
    policy_sets_prefixed_parameter = (
        select(ParameterValue.id)
        .join(Parameter, col(Parameter.id) == col(ParameterValue.parameter_id))
        .where(col(ParameterValue.policy_id) == col(Policy.id), sets_prefixed_parameter)
        .exists()
    )
    return list(
        session.exec(
            select(Policy.id)
            .where(policy_sets_prefixed_parameter)
            .order_by(col(Policy.created_at), col(Policy.id))
        ).all()
    )


def read_policy_for_split(
    session: Session, policy_id: UUID, *, lock: bool
) -> Policy | None:
    """Return the stored policy, or None.

    With ``lock``, the row is selected FOR UPDATE, so until the transaction
    ends no other transaction can add a row that names it (a foreign key's
    check locks the row it names) or delete it.
    """
    statement = select(Policy).where(Policy.id == policy_id)
    if lock:
        statement = statement.with_for_update()
    return session.exec(statement).one_or_none()


def read_mappings_naming_policy(
    session: Session, policy_id: UUID, *, lock: bool
) -> list[LegacyPolicyMapping]:
    """Return the legacy policy mappings that name the policy, by v1 policy ID.

    With ``lock``, they are selected FOR UPDATE, as the v1-to-v2 copy selects
    a mapping it reads.
    """
    statement = (
        select(LegacyPolicyMapping)
        .where(LegacyPolicyMapping.policy_id == policy_id)
        .order_by(
            col(LegacyPolicyMapping.country_id),
            col(LegacyPolicyMapping.legacy_policy_id),
        )
    )
    if lock:
        statement = statement.with_for_update()
    return list(session.exec(statement).all())


def read_saved_policies_naming_policy(
    session: Session, policy_id: UUID
) -> list[UserPolicy]:
    """Return the saved policies that name the policy, oldest first, unlocked.

    The split locks each only just before saving its owner's dynamic
    (``read_saved_policy_for_update``).
    """
    return list(
        session.exec(
            select(UserPolicy)
            .where(UserPolicy.policy_id == policy_id)
            .order_by(col(UserPolicy.created_at), col(UserPolicy.id))
        ).all()
    )


def read_saved_policy_for_update(
    session: Session, saved_policy_id: UUID
) -> UserPolicy | None:
    """Return the saved policy, selected FOR UPDATE, or None if it was deleted."""
    return session.exec(
        select(UserPolicy).where(UserPolicy.id == saved_policy_id).with_for_update()
    ).one_or_none()


def count_rows_naming_policy(session: Session, policy_id: UUID) -> CopyReferences:
    """Return how many simulations, reports and household jobs name the policy."""
    simulations = session.exec(
        select(func.count())
        .select_from(Simulation)
        .where(col(Simulation.policy_id) == policy_id)
    ).one()
    reports = session.exec(
        select(func.count())
        .select_from(Report)
        .where(col(Report.policy_id) == policy_id)
    ).one()
    household_jobs = session.exec(
        select(func.count())
        .select_from(HouseholdJob)
        .where(col(HouseholdJob.policy_id) == policy_id)
    ).one()
    return CopyReferences(
        simulations=simulations, reports=reports, household_jobs=household_jobs
    )


def read_saved_dynamic_with_name(
    session: Session,
    *,
    user_id: UUID,
    country_id: str,
    dynamic_id: UUID,
    name: str | None,
) -> UserDynamic | None:
    """Return the user's oldest saved dynamic of this dynamic with this name, or None.

    A null name matches only a null name.
    """
    name_matches = (
        col(UserDynamic.name).is_(None) if name is None else UserDynamic.name == name
    )
    return session.exec(
        select(UserDynamic)
        .where(
            UserDynamic.user_id == user_id,
            UserDynamic.country_id == country_id,
            UserDynamic.dynamic_id == dynamic_id,
            name_matches,
        )
        .order_by(col(UserDynamic.created_at), col(UserDynamic.id))
        .limit(1)
    ).first()
