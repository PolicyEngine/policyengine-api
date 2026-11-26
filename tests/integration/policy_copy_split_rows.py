"""Rows for the policy copy split's PostgreSQL tests, written and removed as the owner.

Each test's catalog has a model of its own (``Scenario``), so a test removes
only the rows it wrote, although the split reads every stored policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import delete, or_
from sqlmodel import Session, col, select

from policyengine_api.data.v2.models import (
    Dataset,
    Dynamic,
    Household,
    HouseholdJob,
    LegacyPolicyMapping,
    Parameter,
    ParameterValue,
    Policy,
    Report,
    Simulation,
    TaxBenefitModel,
    TaxBenefitModelVersion,
    User,
    UserDynamic,
    UserPolicy,
)
from policyengine_api.services.v2.dynamics.services import create_resolved_dynamic
from policyengine_api.services.v2.dynamics.types import ResolvedDynamicCreationInput
from policyengine_api.services.v2.policies.services import create_resolved_policy
from policyengine_api.services.v2.policies.types import ResolvedPolicyCreationInput

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.orm import sessionmaker

    from policyengine_api.services.v2.policy_copy_split.types import PolicyCopySplit

CATALOG_VERSION = "6.17.1"
START_2026 = datetime(2026, 1, 1, tzinfo=UTC)
END_2026 = datetime(2026, 12, 31, tzinfo=UTC)


@dataclass
class Scenario:
    """One test's model, catalog version and parameters, and what it stored."""

    country_id: str
    model_id: UUID
    version_id: UUID
    parameter_ids: dict[str, UUID]
    policyengine_version: str = CATALOG_VERSION
    user_ids: list[UUID] = field(default_factory=list)
    legacy_policy_ids: list[int] = field(default_factory=list)
    household_ids: list[UUID] = field(default_factory=list)

    def parameter_value(
        self, name: str, *, value: object, end_date: datetime | None = END_2026
    ) -> dict[str, object]:
        return {
            "parameter_id": self.parameter_ids[name],
            "value": value,
            "start_date": START_2026,
            "end_date": end_date,
        }

    def content(self, *values: dict[str, object]) -> dict[str, object]:
        return {
            "country_id": self.country_id,
            "tax_benefit_model_id": self.model_id,
            "tax_benefit_model_version_id": self.version_id,
            "policyengine_version": self.policyengine_version,
            "parameter_values": list(values),
        }


def store_catalog(
    owner_sessions: sessionmaker[Session], country_id: str, names: list[str]
) -> Scenario:
    with owner_sessions() as session:
        model = TaxBenefitModel(name=f"split-{country_id}-{uuid4().hex[:16]}")
        version = TaxBenefitModelVersion(
            model=model,
            version=CATALOG_VERSION,
            current_law_id=1,
            metadata_time_periods=[2026],
        )
        parameters = [
            Parameter(name=name, tax_benefit_model_version=version) for name in names
        ]
        session.add_all(parameters)
        session.commit()
        return Scenario(
            country_id=country_id,
            model_id=model.id,
            version_id=version.id,
            parameter_ids={parameter.name: parameter.id for parameter in parameters},
        )


def remove_scenario(owner_sessions: sessionmaker[Session], scenario: Scenario) -> None:
    policy_ids = select(Policy.id).where(
        Policy.tax_benefit_model_id == scenario.model_id
    )
    dynamic_ids = select(Dynamic.id).where(
        Dynamic.tax_benefit_model_id == scenario.model_id
    )
    with owner_sessions() as session:
        session.execute(
            delete(UserDynamic).where(col(UserDynamic.dynamic_id).in_(dynamic_ids))
        )
        session.execute(
            delete(UserPolicy).where(col(UserPolicy.policy_id).in_(policy_ids))
        )
        session.execute(delete(User).where(col(User.id).in_(scenario.user_ids)))
        session.execute(
            delete(LegacyPolicyMapping).where(
                or_(
                    col(LegacyPolicyMapping.policy_id).in_(policy_ids),
                    col(LegacyPolicyMapping.dynamic_id).in_(dynamic_ids),
                )
            )
        )
        session.execute(
            delete(Report).where(Report.tax_benefit_model_id == scenario.model_id)
        )
        session.execute(
            delete(Simulation).where(
                Simulation.tax_benefit_model_version_id == scenario.version_id
            )
        )
        session.execute(
            delete(Dataset).where(
                Dataset.tax_benefit_model_version_id == scenario.version_id
            )
        )
        session.execute(
            delete(Policy).where(Policy.tax_benefit_model_id == scenario.model_id)
        )
        session.execute(
            delete(Dynamic).where(Dynamic.tax_benefit_model_id == scenario.model_id)
        )
        version_ids = select(TaxBenefitModelVersion.id).where(
            TaxBenefitModelVersion.model_id == scenario.model_id
        )
        session.execute(
            delete(HouseholdJob).where(
                col(HouseholdJob.tax_benefit_model_version_id).in_(version_ids)
            )
        )
        session.execute(
            delete(Household).where(col(Household.id).in_(scenario.household_ids))
        )
        parameter_ids = select(Parameter.id).where(
            col(Parameter.tax_benefit_model_version_id).in_(version_ids)
        )
        session.execute(
            delete(ParameterValue).where(
                col(ParameterValue.parameter_id).in_(parameter_ids)
            )
        )
        session.execute(
            delete(Parameter).where(
                col(Parameter.tax_benefit_model_version_id).in_(version_ids)
            )
        )
        session.execute(
            delete(TaxBenefitModelVersion).where(
                TaxBenefitModelVersion.model_id == scenario.model_id
            )
        )
        session.execute(
            delete(TaxBenefitModel).where(TaxBenefitModel.id == scenario.model_id)
        )
        session.commit()


def store_other_version(
    owner_sessions: sessionmaker[Session], scenario: Scenario, names: list[str]
) -> Scenario:
    """Store another catalog version of the scenario's model, with these parameters."""
    with owner_sessions() as session:
        version = TaxBenefitModelVersion(
            model_id=scenario.model_id,
            version="6.20.0",
            current_law_id=1,
            metadata_time_periods=[2026],
        )
        parameters = [
            Parameter(name=name, tax_benefit_model_version=version) for name in names
        ]
        session.add_all(parameters)
        session.commit()
        return Scenario(
            country_id=scenario.country_id,
            model_id=scenario.model_id,
            version_id=version.id,
            parameter_ids={parameter.name: parameter.id for parameter in parameters},
            policyengine_version="6.20.0",
        )


def store_policy(
    owner_sessions: sessionmaker[Session],
    scenario: Scenario,
    *values: dict[str, object],
) -> UUID:
    """Store a policy as the v1-to-v2 copy did before C1 · 36: no split."""
    with owner_sessions() as session:
        result = create_resolved_policy(
            session,
            ResolvedPolicyCreationInput.model_validate(scenario.content(*values)),
        )
        session.commit()
    return result.policy_id


def store_dynamic(
    owner_sessions: sessionmaker[Session],
    scenario: Scenario,
    *values: dict[str, object],
) -> UUID:
    with owner_sessions() as session:
        result = create_resolved_dynamic(
            session,
            ResolvedDynamicCreationInput.model_validate(scenario.content(*values)),
        )
        session.commit()
    return result.dynamic_id


def store_mapping(
    owner_sessions: sessionmaker[Session],
    scenario: Scenario,
    *,
    policy_id: UUID,
    dynamic_id: UUID | None = None,
) -> int:
    legacy_policy_id = 900_000_000 + uuid4().int % 100_000_000
    with owner_sessions() as session:
        session.add(
            LegacyPolicyMapping(
                country_id=scenario.country_id,
                legacy_policy_id=legacy_policy_id,
                policy_id=policy_id,
                dynamic_id=dynamic_id,
                source_policy_hash=f"legacy-hash-{legacy_policy_id}",
            )
        )
        session.commit()
    scenario.legacy_policy_ids.append(legacy_policy_id)
    return legacy_policy_id


def store_user(owner_sessions: sessionmaker[Session], scenario: Scenario) -> UUID:
    with owner_sessions() as session:
        user = User(user_type="unauthenticated")
        session.add(user)
        session.commit()
        scenario.user_ids.append(user.id)
        return user.id


def store_saved_policy(
    owner_sessions: sessionmaker[Session],
    scenario: Scenario,
    **saved_policy_fields: object,
) -> UUID:
    """Store a saved policy with the given user, policy, name and other fields."""
    with owner_sessions() as session:
        saved_policy = UserPolicy(country_id=scenario.country_id, **saved_policy_fields)
        session.add(saved_policy)
        session.commit()
        return saved_policy.id


def stored_values(
    owner_sessions: sessionmaker[Session], *, policy_id=None, dynamic_id=None
) -> set:
    """Each value a policy or dynamic sets: its parameter, value and end date."""
    with owner_sessions() as session:
        owner_column = (
            ParameterValue.policy_id
            if dynamic_id is None
            else ParameterValue.dynamic_id
        )
        rows = session.exec(
            select(ParameterValue).where(owner_column == (policy_id or dynamic_id))
        ).all()
        return {(row.parameter_id, row.value_json, row.end_date) for row in rows}


def stored_mapping(
    owner_sessions: sessionmaker[Session], scenario: Scenario, legacy_policy_id: int
):
    with owner_sessions() as session:
        return session.exec(
            select(LegacyPolicyMapping).where(
                LegacyPolicyMapping.country_id == scenario.country_id,
                LegacyPolicyMapping.legacy_policy_id == legacy_policy_id,
            )
        ).one()


def saved_policy_target(
    owner_sessions: sessionmaker[Session], saved_policy_id: UUID
) -> UUID:
    with owner_sessions() as session:
        return session.get(UserPolicy, saved_policy_id).policy_id


def saved_dynamics_of(
    owner_sessions: sessionmaker[Session], user_id: UUID
) -> list[UserDynamic]:
    with owner_sessions() as session:
        return list(
            session.exec(
                select(UserDynamic)
                .where(UserDynamic.user_id == user_id)
                .order_by(col(UserDynamic.created_at), col(UserDynamic.id))
            ).all()
        )


def policy_exists(owner_sessions: sessionmaker[Session], policy_id: UUID) -> bool:
    with owner_sessions() as session:
        return session.get(Policy, policy_id) is not None


def split_for(splits: Iterable[PolicyCopySplit], policy_id: UUID) -> PolicyCopySplit:
    [split] = [split for split in splits if split.old_policy_id == policy_id]
    return split
