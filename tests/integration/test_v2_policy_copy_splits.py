"""PostgreSQL tests for C1 · 48's split of stored policies holding model assumptions.

The command runs as the temporary role C1 · 49 creates, holding exactly
``POLICY_COPY_SPLIT_PRIVILEGES``, so a statement those grants don't allow
fails here. Rows are written and removed as the disposable database's
superuser. Each test's catalog has a model of its own, and assertions look
only at the rows the test wrote, since the command reads every stored policy.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, delete, or_
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from sqlmodel import Session, col, select

from policyengine_api.data.v2.database import unpooled_v2_read_only_sessions
from policyengine_api.data.v2.models import (
    Dataset,
    Dynamic,
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
from policyengine_api.data.v2.privilege_reconciliation import (
    apply_declared_privileges,
    create_missing_roles,
)
from policyengine_api.data.v2.privileges import (
    POLICY_COPY_SPLIT_PRIVILEGES,
    POLICY_COPY_SPLIT_ROLE,
)
from policyengine_api.services.v2.dynamics.services import create_resolved_dynamic
from policyengine_api.services.v2.dynamics.types import ResolvedDynamicCreationInput
from policyengine_api.services.v2.policies.services import create_resolved_policy
from policyengine_api.services.v2.policies.types import ResolvedPolicyCreationInput
from policyengine_api.services.v2.policy_copy_split.database_session import (
    PolicyCopySplitDatabaseSession,
)
from policyengine_api.services.v2.policy_copy_split.services import (
    V2PolicyCopySplitService,
    read_policy_copy_ids,
    split_policy_copy_in_session,
)
from policyengine_api.services.v2.policy_copy_split.types import (
    PolicyCopyOutcome,
    PolicyCopyRefusalReason,
    PolicyCopySplit,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Engine

CATALOG_VERSION = "6.17.1"
US_TAX_RATE = "gov.irs.income.rate"
US_INCOME_ELASTICITY = "gov.simulation.labor_supply_responses.elasticities.income"
US_MTR_DELTA = "simulation.marginal_tax_rate_delta"
UK_TAX_RATE = "gov.hmrc.income_tax.rates.uk[0].rate"
UK_INCOME_ELASTICITY = "gov.simulation.labour_supply_responses.income_elasticity"
UK_OBR_SWITCH = "gov.dynamic.obr_labour_supply_assumptions"
START_2026 = datetime(2026, 1, 1, tzinfo=UTC)
END_2026 = datetime(2026, 12, 31, tzinfo=UTC)


@pytest.fixture(scope="module")
def owner_engine(disposable_v2_database_url: str) -> Iterator[Engine]:
    engine = create_engine(disposable_v2_database_url, poolclass=NullPool)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def split_role_engine(owner_engine: Engine, v2_engine_as_role) -> Iterator[Engine]:
    """Yield an engine acting as the temporary role, with only its declared grants."""
    with owner_engine.begin() as connection:
        create_missing_roles(connection, [POLICY_COPY_SPLIT_ROLE])
        plan, _default_privileges = apply_declared_privileges(
            connection, {POLICY_COPY_SPLIT_ROLE: POLICY_COPY_SPLIT_PRIVILEGES}
        )
    assert plan.can_apply
    engine = v2_engine_as_role(POLICY_COPY_SPLIT_ROLE, poolclass=NullPool)
    try:
        yield engine
    finally:
        engine.dispose()


def _service(engine: Engine, *, read_only: bool = False) -> V2PolicyCopySplitService:
    bind = engine.execution_options(postgresql_readonly=True) if read_only else engine
    return V2PolicyCopySplitService(
        PolicyCopySplitDatabaseSession(
            sessionmaker(bind=bind, class_=Session, expire_on_commit=False)
        )
    )


@dataclass
class Scenario:
    """One test's model, catalog version and parameters, and what it stored."""

    country_id: str
    model_id: UUID
    version_id: UUID
    parameter_ids: dict[str, UUID]
    user_ids: list[UUID] = field(default_factory=list)
    legacy_policy_ids: list[int] = field(default_factory=list)

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
            "policyengine_version": CATALOG_VERSION,
            "parameter_values": list(values),
        }


def _store_catalog(owner_engine: Engine, country_id: str, names: list[str]) -> Scenario:
    with Session(owner_engine) as session:
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


def _remove(owner_engine: Engine, scenario: Scenario) -> None:
    policy_ids = select(Policy.id).where(
        Policy.tax_benefit_model_id == scenario.model_id
    )
    dynamic_ids = select(Dynamic.id).where(
        Dynamic.tax_benefit_model_id == scenario.model_id
    )
    with Session(owner_engine) as session:
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
        session.execute(
            delete(ParameterValue).where(
                col(ParameterValue.parameter_id).in_(scenario.parameter_ids.values())
            )
        )
        session.execute(
            delete(Parameter).where(
                Parameter.tax_benefit_model_version_id == scenario.version_id
            )
        )
        session.execute(
            delete(TaxBenefitModelVersion).where(
                TaxBenefitModelVersion.id == scenario.version_id
            )
        )
        session.execute(
            delete(TaxBenefitModel).where(TaxBenefitModel.id == scenario.model_id)
        )
        session.commit()


@pytest.fixture
def us_scenario(owner_engine: Engine) -> Iterator[Scenario]:
    scenario = _store_catalog(
        owner_engine, "us", [US_TAX_RATE, US_INCOME_ELASTICITY, US_MTR_DELTA]
    )
    try:
        yield scenario
    finally:
        _remove(owner_engine, scenario)


@pytest.fixture
def uk_scenario(owner_engine: Engine) -> Iterator[Scenario]:
    scenario = _store_catalog(
        owner_engine, "uk", [UK_TAX_RATE, UK_INCOME_ELASTICITY, UK_OBR_SWITCH]
    )
    try:
        yield scenario
    finally:
        _remove(owner_engine, scenario)


def _store_policy(
    owner_engine: Engine, scenario: Scenario, *values: dict[str, object]
) -> UUID:
    """Store a policy as the v1-to-v2 copy did before C1 · 36: no split."""
    with Session(owner_engine) as session:
        result = create_resolved_policy(
            session,
            ResolvedPolicyCreationInput.model_validate(scenario.content(*values)),
        )
        session.commit()
    return result.policy_id


def _store_dynamic(
    owner_engine: Engine, scenario: Scenario, *values: dict[str, object]
) -> UUID:
    with Session(owner_engine) as session:
        result = create_resolved_dynamic(
            session,
            ResolvedDynamicCreationInput.model_validate(scenario.content(*values)),
        )
        session.commit()
    return result.dynamic_id


def _store_mapping(
    owner_engine: Engine,
    scenario: Scenario,
    *,
    policy_id: UUID,
    dynamic_id: UUID | None = None,
) -> int:
    legacy_policy_id = 900_000_000 + uuid4().int % 100_000_000
    with Session(owner_engine) as session:
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


def _store_user(owner_engine: Engine, scenario: Scenario) -> UUID:
    with Session(owner_engine) as session:
        user = User(user_type="unauthenticated")
        session.add(user)
        session.commit()
        scenario.user_ids.append(user.id)
        return user.id


def _store_saved_policy(
    owner_engine: Engine, scenario: Scenario, **saved_policy_fields: object
) -> UUID:
    """Store a saved policy with the given user, policy, name and other fields."""
    with Session(owner_engine) as session:
        saved_policy = UserPolicy(country_id=scenario.country_id, **saved_policy_fields)
        session.add(saved_policy)
        session.commit()
        return saved_policy.id


def _values(owner_engine: Engine, *, policy_id=None, dynamic_id=None) -> set:
    """Each value a policy or dynamic sets: its parameter, value and end date."""
    with Session(owner_engine) as session:
        owner_column = (
            ParameterValue.policy_id
            if dynamic_id is None
            else ParameterValue.dynamic_id
        )
        rows = session.exec(
            select(ParameterValue).where(owner_column == (policy_id or dynamic_id))
        ).all()
        return {(row.parameter_id, row.value_json, row.end_date) for row in rows}


def _mapping(owner_engine: Engine, scenario: Scenario, legacy_policy_id: int):
    with Session(owner_engine) as session:
        return session.exec(
            select(LegacyPolicyMapping).where(
                LegacyPolicyMapping.country_id == scenario.country_id,
                LegacyPolicyMapping.legacy_policy_id == legacy_policy_id,
            )
        ).one()


def _saved_policy_target(owner_engine: Engine, saved_policy_id: UUID) -> UUID:
    with Session(owner_engine) as session:
        return session.get(UserPolicy, saved_policy_id).policy_id


def _saved_dynamics(owner_engine: Engine, user_id: UUID) -> list[UserDynamic]:
    with Session(owner_engine) as session:
        return list(
            session.exec(
                select(UserDynamic)
                .where(UserDynamic.user_id == user_id)
                .order_by(col(UserDynamic.created_at), col(UserDynamic.id))
            ).all()
        )


def _policy_exists(owner_engine: Engine, policy_id: UUID) -> bool:
    with Session(owner_engine) as session:
        return session.get(Policy, policy_id) is not None


def _result_for(splits, policy_id: UUID) -> PolicyCopySplit:
    [split] = [split for split in splits if split.old_policy_id == policy_id]
    return split


def test_a_us_copy_is_split_re_pointed_given_a_saved_dynamic_and_deleted(
    owner_engine: Engine, split_role_engine: Engine, us_scenario: Scenario
) -> None:
    scenario = us_scenario
    old_copy_id = _store_policy(
        owner_engine,
        scenario,
        scenario.parameter_value(US_TAX_RATE, value=0.3),
        scenario.parameter_value(US_INCOME_ELASTICITY, value=0.25),
        scenario.parameter_value(US_MTR_DELTA, value=0.01, end_date=None),
    )
    legacy_policy_id = _store_mapping(owner_engine, scenario, policy_id=old_copy_id)
    user_id = _store_user(owner_engine, scenario)
    saved_policy_id = _store_saved_policy(
        owner_engine,
        scenario,
        user_id=user_id,
        policy_id=old_copy_id,
        name="My reform",
        legacy_policy_id=legacy_policy_id,
        description="Raises the rate, with labour supply responses",
    )

    split = _result_for(
        list(_service(split_role_engine).split_policy_copies()), old_copy_id
    )

    assert split.applied
    assert split.outcome is PolicyCopyOutcome.DELETED
    assert split.country_id == "us"
    assert split.policyengine_version == CATALOG_VERSION
    assert split.policy is not None
    assert split.policy.created
    assert split.dynamic is not None
    assert split.dynamic.created
    new_policy_id, new_dynamic_id = split.policy.id, split.dynamic.id
    assert not _policy_exists(owner_engine, old_copy_id)
    assert _values(owner_engine, policy_id=old_copy_id) == set()
    assert _values(owner_engine, policy_id=new_policy_id) == {
        (scenario.parameter_ids[US_TAX_RATE], 0.3, END_2026)
    }
    assert _values(owner_engine, dynamic_id=new_dynamic_id) == {
        (scenario.parameter_ids[US_INCOME_ELASTICITY], 0.25, END_2026),
        (scenario.parameter_ids[US_MTR_DELTA], 0.01, None),
    }
    mapping = _mapping(owner_engine, scenario, legacy_policy_id)
    assert (mapping.policy_id, mapping.dynamic_id) == (new_policy_id, new_dynamic_id)
    [repointed_mapping] = split.mappings
    assert repointed_mapping.legacy_policy_id == legacy_policy_id
    assert repointed_mapping.previous_dynamic_id is None
    assert repointed_mapping.dynamic.id == new_dynamic_id
    assert _saved_policy_target(owner_engine, saved_policy_id) == new_policy_id
    [saved_dynamic] = _saved_dynamics(owner_engine, user_id)
    assert (saved_dynamic.dynamic_id, saved_dynamic.country_id) == (
        new_dynamic_id,
        "us",
    )
    assert (saved_dynamic.name, saved_dynamic.description) == ("My reform", None)
    [repointed_saved_policy] = split.saved_policies
    assert repointed_saved_policy.user_policy_id == saved_policy_id
    assert repointed_saved_policy.saved_dynamic_id == saved_dynamic.id
    assert repointed_saved_policy.saved_dynamic_created
    with Session(split_role_engine) as session:
        assert old_copy_id not in read_policy_copy_ids(session)

    second_run = list(_service(split_role_engine).split_policy_copies())

    assert old_copy_id not in {split.old_policy_id for split in second_run}
    mapping_after = _mapping(owner_engine, scenario, legacy_policy_id)
    assert (mapping_after.policy_id, mapping_after.dynamic_id) == (
        new_policy_id,
        new_dynamic_id,
    )
    assert _saved_policy_target(owner_engine, saved_policy_id) == new_policy_id
    assert [row.id for row in _saved_dynamics(owner_engine, user_id)] == [
        saved_dynamic.id
    ]


def test_a_uk_copy_of_only_model_assumptions_points_at_an_empty_policy(
    owner_engine: Engine, split_role_engine: Engine, uk_scenario: Scenario
) -> None:
    scenario = uk_scenario
    old_copy_id = _store_policy(
        owner_engine, scenario, scenario.parameter_value(UK_OBR_SWITCH, value=False)
    )
    legacy_policy_id = _store_mapping(owner_engine, scenario, policy_id=old_copy_id)

    split = _result_for(
        list(_service(split_role_engine).split_policy_copies()), old_copy_id
    )

    assert split.outcome is PolicyCopyOutcome.DELETED
    mapping = _mapping(owner_engine, scenario, legacy_policy_id)
    assert mapping.policy_id == split.policy.id
    assert _values(owner_engine, policy_id=mapping.policy_id) == set()
    with Session(owner_engine) as session:
        empty_policy = session.get(Policy, mapping.policy_id)
        assert empty_policy.tax_benefit_model_version_id == scenario.version_id
    assert _values(owner_engine, dynamic_id=mapping.dynamic_id) == {
        (scenario.parameter_ids[UK_OBR_SWITCH], False, END_2026)
    }
    assert not _policy_exists(owner_engine, old_copy_id)


def test_a_mapping_that_already_names_a_dynamic_gets_one_merged_dynamic(
    owner_engine: Engine, split_role_engine: Engine, uk_scenario: Scenario
) -> None:
    scenario = uk_scenario
    old_copy_id = _store_policy(
        owner_engine,
        scenario,
        scenario.parameter_value(UK_TAX_RATE, value=0.21),
        scenario.parameter_value(UK_OBR_SWITCH, value=False),
    )
    earlier_dynamic_id = _store_dynamic(
        owner_engine,
        scenario,
        scenario.parameter_value(UK_INCOME_ELASTICITY, value=0.1),
    )
    legacy_policy_id = _store_mapping(
        owner_engine, scenario, policy_id=old_copy_id, dynamic_id=earlier_dynamic_id
    )
    user_id = _store_user(owner_engine, scenario)
    mapped_saved_policy_id = _store_saved_policy(
        owner_engine,
        scenario,
        user_id=user_id,
        policy_id=old_copy_id,
        name="Copied from v1",
        legacy_policy_id=legacy_policy_id,
    )
    native_saved_policy_id = _store_saved_policy(
        owner_engine, scenario, user_id=user_id, policy_id=old_copy_id, name="Native"
    )

    split = _result_for(
        list(_service(split_role_engine).split_policy_copies()), old_copy_id
    )

    assert split.outcome is PolicyCopyOutcome.DELETED
    mapping = _mapping(owner_engine, scenario, legacy_policy_id)
    assert mapping.policy_id == split.policy.id
    assert _values(owner_engine, policy_id=mapping.policy_id) == {
        (scenario.parameter_ids[UK_TAX_RATE], 0.21, END_2026)
    }
    merged_dynamic_id = mapping.dynamic_id
    assert merged_dynamic_id not in {earlier_dynamic_id, split.dynamic.id}
    assert _values(owner_engine, dynamic_id=merged_dynamic_id) == {
        (scenario.parameter_ids[UK_INCOME_ELASTICITY], 0.1, END_2026),
        (scenario.parameter_ids[UK_OBR_SWITCH], False, END_2026),
    }
    assert _values(owner_engine, dynamic_id=split.dynamic.id) == {
        (scenario.parameter_ids[UK_OBR_SWITCH], False, END_2026)
    }
    [repointed_mapping] = split.mappings
    assert repointed_mapping.previous_dynamic_id == earlier_dynamic_id
    assert repointed_mapping.dynamic.id == merged_dynamic_id
    saved_dynamics = {
        row.name: row.dynamic_id for row in _saved_dynamics(owner_engine, user_id)
    }
    assert saved_dynamics == {
        "Copied from v1": merged_dynamic_id,
        "Native": split.dynamic.id,
    }
    for saved_policy_id in (mapped_saved_policy_id, native_saved_policy_id):
        assert _saved_policy_target(owner_engine, saved_policy_id) == mapping.policy_id
    with Session(owner_engine) as session:
        assert session.get(Dynamic, earlier_dynamic_id) is not None


def test_a_copy_a_report_names_is_split_and_re_pointed_but_kept(
    owner_engine: Engine, split_role_engine: Engine, us_scenario: Scenario
) -> None:
    scenario = us_scenario
    old_copy_id = _store_policy(
        owner_engine,
        scenario,
        scenario.parameter_value(US_TAX_RATE, value=0.3),
        scenario.parameter_value(US_INCOME_ELASTICITY, value=0.25),
    )
    legacy_policy_id = _store_mapping(owner_engine, scenario, policy_id=old_copy_id)
    user_id = _store_user(owner_engine, scenario)
    saved_policy_id = _store_saved_policy(
        owner_engine, scenario, user_id=user_id, policy_id=old_copy_id, name="Kept"
    )
    with Session(owner_engine) as session:
        report = Report(
            country="us",
            tax_benefit_model_id=scenario.model_id,
            policy_id=old_copy_id,
        )
        session.add(report)
        session.commit()
        report_id = report.id

    split = _result_for(
        list(_service(split_role_engine).split_policy_copies()), old_copy_id
    )

    assert split.outcome is PolicyCopyOutcome.KEPT
    assert (
        split.references.simulations,
        split.references.reports,
        split.references.household_jobs,
    ) == (0, 1, 0)
    assert _policy_exists(owner_engine, old_copy_id)
    assert len(_values(owner_engine, policy_id=old_copy_id)) == 2
    with Session(owner_engine) as session:
        assert session.get(Report, report_id).policy_id == old_copy_id
    mapping = _mapping(owner_engine, scenario, legacy_policy_id)
    assert (mapping.policy_id, mapping.dynamic_id) == (
        split.policy.id,
        split.dynamic.id,
    )
    assert _saved_policy_target(owner_engine, saved_policy_id) == split.policy.id
    [saved_dynamic] = _saved_dynamics(owner_engine, user_id)
    with Session(split_role_engine) as session:
        assert old_copy_id in read_policy_copy_ids(session)

    second_split = _result_for(
        list(_service(split_role_engine).split_policy_copies()), old_copy_id
    )

    assert second_split.outcome is PolicyCopyOutcome.KEPT
    assert second_split.mappings == ()
    assert second_split.saved_policies == ()
    assert [row.id for row in _saved_dynamics(owner_engine, user_id)] == [
        saved_dynamic.id
    ]
    with Session(owner_engine) as session:
        session.execute(delete(Report).where(Report.id == report_id))
        session.commit()


def test_a_conflicting_merge_refuses_the_copy_and_changes_nothing(
    owner_engine: Engine, split_role_engine: Engine, uk_scenario: Scenario
) -> None:
    scenario = uk_scenario
    old_copy_id = _store_policy(
        owner_engine,
        scenario,
        scenario.parameter_value(UK_TAX_RATE, value=0.21),
        scenario.parameter_value(UK_INCOME_ELASTICITY, value=0.2),
    )
    earlier_dynamic_id = _store_dynamic(
        owner_engine,
        scenario,
        scenario.parameter_value(UK_INCOME_ELASTICITY, value=0.1),
    )
    legacy_policy_id = _store_mapping(
        owner_engine, scenario, policy_id=old_copy_id, dynamic_id=earlier_dynamic_id
    )
    user_id = _store_user(owner_engine, scenario)
    saved_policy_id = _store_saved_policy(
        owner_engine,
        scenario,
        user_id=user_id,
        policy_id=old_copy_id,
        name="Conflicting",
        legacy_policy_id=legacy_policy_id,
    )

    split = _result_for(
        list(_service(split_role_engine).split_policy_copies()), old_copy_id
    )

    assert split.outcome is PolicyCopyOutcome.REFUSED
    assert split.refusal_reason is PolicyCopyRefusalReason.CONFLICTING_DYNAMIC_VALUES
    assert _policy_exists(owner_engine, old_copy_id)
    mapping = _mapping(owner_engine, scenario, legacy_policy_id)
    assert (mapping.policy_id, mapping.dynamic_id) == (old_copy_id, earlier_dynamic_id)
    assert _saved_policy_target(owner_engine, saved_policy_id) == old_copy_id
    assert _saved_dynamics(owner_engine, user_id) == []
    with Session(owner_engine) as session:
        stored = session.exec(
            select(Policy.id).where(Policy.tax_benefit_model_id == scenario.model_id)
        ).all()
        assert list(stored) == [old_copy_id]
        dynamics = session.exec(
            select(Dynamic.id).where(Dynamic.tax_benefit_model_id == scenario.model_id)
        ).all()
        assert list(dynamics) == [earlier_dynamic_id]


def test_the_listing_reads_only_and_reports_what_would_change(
    owner_engine: Engine, split_role_engine: Engine, us_scenario: Scenario
) -> None:
    scenario = us_scenario
    stored_policy_part_id = _store_policy(
        owner_engine, scenario, scenario.parameter_value(US_TAX_RATE, value=0.3)
    )
    old_copy_id = _store_policy(
        owner_engine,
        scenario,
        scenario.parameter_value(US_TAX_RATE, value=0.3),
        scenario.parameter_value(US_INCOME_ELASTICITY, value=0.25),
    )
    legacy_policy_id = _store_mapping(owner_engine, scenario, policy_id=old_copy_id)
    user_id = _store_user(owner_engine, scenario)
    saved_policy_id = _store_saved_policy(
        owner_engine, scenario, user_id=user_id, policy_id=old_copy_id, name="Listed"
    )

    split = _result_for(
        _service(split_role_engine, read_only=True).list_policy_copy_splits(),
        old_copy_id,
    )

    assert not split.applied
    assert split.outcome is PolicyCopyOutcome.DELETED
    assert (split.policy.id, split.policy.created) == (stored_policy_part_id, False)
    assert (split.dynamic.id, split.dynamic.created) == (None, True)
    [listed_mapping] = split.mappings
    assert listed_mapping.legacy_policy_id == legacy_policy_id
    assert listed_mapping.dynamic.content_hash == split.dynamic.content_hash
    [listed_saved_policy] = split.saved_policies
    assert listed_saved_policy.user_policy_id == saved_policy_id
    assert listed_saved_policy.saved_dynamic_id is None
    assert listed_saved_policy.saved_dynamic_created
    assert _policy_exists(owner_engine, old_copy_id)
    mapping = _mapping(owner_engine, scenario, legacy_policy_id)
    assert (mapping.policy_id, mapping.dynamic_id) == (old_copy_id, None)
    assert _saved_policy_target(owner_engine, saved_policy_id) == old_copy_id
    assert _saved_dynamics(owner_engine, user_id) == []
    with Session(owner_engine) as session:
        dynamics = session.exec(
            select(Dynamic.id).where(Dynamic.tax_benefit_model_id == scenario.model_id)
        ).all()
        assert dynamics == []


def test_an_identical_saved_dynamic_is_reused_and_another_name_gets_its_own(
    owner_engine: Engine, split_role_engine: Engine, us_scenario: Scenario
) -> None:
    scenario = us_scenario
    old_copy_id = _store_policy(
        owner_engine,
        scenario,
        scenario.parameter_value(US_TAX_RATE, value=0.3),
        scenario.parameter_value(US_INCOME_ELASTICITY, value=0.25),
    )
    user_id = _store_user(owner_engine, scenario)
    first_id, second_id, other_id, unnamed_id, also_unnamed_id = (
        _store_saved_policy(
            owner_engine, scenario, user_id=user_id, policy_id=old_copy_id, name=name
        )
        for name in ("Reform A", "Reform A", "Reform B", None, None)
    )

    split = _result_for(
        list(_service(split_role_engine).split_policy_copies()), old_copy_id
    )

    by_saved_policy = {
        repointed.user_policy_id: repointed for repointed in split.saved_policies
    }
    assert by_saved_policy[first_id].saved_dynamic_created
    assert not by_saved_policy[second_id].saved_dynamic_created
    assert (
        by_saved_policy[second_id].saved_dynamic_id
        == by_saved_policy[first_id].saved_dynamic_id
    )
    assert by_saved_policy[other_id].saved_dynamic_created
    assert by_saved_policy[unnamed_id].saved_dynamic_created
    assert not by_saved_policy[also_unnamed_id].saved_dynamic_created
    assert sorted(
        (row.name or "") for row in _saved_dynamics(owner_engine, user_id)
    ) == ["", "Reform A", "Reform B"]


def test_policies_setting_no_model_assumption_are_left_alone(
    owner_engine: Engine, split_role_engine: Engine, us_scenario: Scenario
) -> None:
    scenario = us_scenario
    policy_id = _store_policy(
        owner_engine, scenario, scenario.parameter_value(US_TAX_RATE, value=0.3)
    )
    legacy_policy_id = _store_mapping(owner_engine, scenario, policy_id=policy_id)

    splits = list(_service(split_role_engine).split_policy_copies())

    assert policy_id not in {split.old_policy_id for split in splits}
    assert _policy_exists(owner_engine, policy_id)
    assert _mapping(owner_engine, scenario, legacy_policy_id).dynamic_id is None


def test_one_copy_splits_in_a_caller_owned_transaction(
    owner_engine: Engine, split_role_engine: Engine, uk_scenario: Scenario
) -> None:
    """D4 · 1's migration reuses the split in a transaction of its own."""
    scenario = uk_scenario
    old_copy_id = _store_policy(
        owner_engine,
        scenario,
        scenario.parameter_value(UK_TAX_RATE, value=0.21),
        scenario.parameter_value(UK_OBR_SWITCH, value=False),
    )
    legacy_policy_id = _store_mapping(owner_engine, scenario, policy_id=old_copy_id)

    with Session(split_role_engine) as session:
        split = split_policy_copy_in_session(session, old_copy_id)
        session.rollback()

    assert split is not None
    assert split.outcome is PolicyCopyOutcome.DELETED
    assert _policy_exists(owner_engine, old_copy_id)
    assert _mapping(owner_engine, scenario, legacy_policy_id).policy_id == old_copy_id

    with Session(split_role_engine) as session:
        assert split_policy_copy_in_session(session, uuid4()) is None


def test_a_copy_a_simulation_names_is_kept(
    owner_engine: Engine, split_role_engine: Engine, us_scenario: Scenario
) -> None:
    scenario = us_scenario
    old_copy_id = _store_policy(
        owner_engine,
        scenario,
        scenario.parameter_value(US_TAX_RATE, value=0.3),
        scenario.parameter_value(US_INCOME_ELASTICITY, value=0.25),
    )
    with Session(owner_engine) as session:
        dataset = Dataset(
            name="split-test-dataset",
            year=2026,
            is_output_dataset=False,
            tax_benefit_model_version_id=scenario.version_id,
        )
        session.add(dataset)
        session.flush()
        simulation = Simulation(
            dataset_id=dataset.id,
            tax_benefit_model_version_id=scenario.version_id,
            policy_id=old_copy_id,
        )
        session.add(simulation)
        session.commit()
        simulation_id = simulation.id

    split = _result_for(
        list(_service(split_role_engine).split_policy_copies()), old_copy_id
    )

    assert split.outcome is PolicyCopyOutcome.KEPT
    assert (
        split.references.simulations,
        split.references.reports,
        split.references.household_jobs,
    ) == (1, 0, 0)
    assert _policy_exists(owner_engine, old_copy_id)
    with Session(owner_engine) as session:
        assert session.get(Simulation, simulation_id).policy_id == old_copy_id


def test_the_split_waits_for_a_live_saved_policy_copy_instead_of_deadlocking(
    owner_engine: Engine, split_role_engine: Engine, us_scenario: Scenario
) -> None:
    """API v1's copy of a v1 saved policy locks the mapping, then names the copy.

    It holds the mapping row FOR UPDATE, then inserts a saved policy naming
    the mapped copy, whose foreign-key check locks the copy's row. The split
    takes the same two locks in the same order, so it waits for the copy to
    commit, and then re-points the saved policy the copy added.
    """
    scenario = us_scenario
    old_copy_id = _store_policy(
        owner_engine,
        scenario,
        scenario.parameter_value(US_TAX_RATE, value=0.3),
        scenario.parameter_value(US_INCOME_ELASTICITY, value=0.25),
    )
    legacy_policy_id = _store_mapping(owner_engine, scenario, policy_id=old_copy_id)
    user_id = _store_user(owner_engine, scenario)
    split_results: list[PolicyCopySplit] = []
    split_errors: list[Exception] = []

    def run_split() -> None:
        try:
            split_results.extend(_service(split_role_engine).split_policy_copies())
        except DBAPIError as error:
            split_errors.append(error)

    split_thread = threading.Thread(target=run_split)
    with Session(owner_engine) as live_copy:
        live_copy.exec(
            select(LegacyPolicyMapping)
            .where(
                LegacyPolicyMapping.country_id == scenario.country_id,
                LegacyPolicyMapping.legacy_policy_id == legacy_policy_id,
            )
            .with_for_update()
        ).one()
        split_thread.start()
        # Give the split time to reach its locks while the mapping is held.
        time.sleep(0.5)
        saved_policy = UserPolicy(
            user_id=user_id,
            country_id=scenario.country_id,
            policy_id=old_copy_id,
            legacy_policy_id=legacy_policy_id,
            name="Saved while splitting",
        )
        live_copy.add(saved_policy)
        live_copy.commit()
        saved_policy_id = saved_policy.id
    split_thread.join(timeout=60)

    assert not split_thread.is_alive()
    assert split_errors == []
    split = _result_for(split_results, old_copy_id)
    assert split.outcome is PolicyCopyOutcome.DELETED
    assert [repointed.user_policy_id for repointed in split.saved_policies] == [
        saved_policy_id
    ]
    assert _saved_policy_target(owner_engine, saved_policy_id) == split.policy.id
    assert not _policy_exists(owner_engine, old_copy_id)


def test_the_listing_reports_rows_an_earlier_copy_creates_as_reused(
    owner_engine: Engine, split_role_engine: Engine, uk_scenario: Scenario
) -> None:
    """Applying commits each copy before the next, so later copies reuse its rows.

    The listing reports what applying then does: the second copy's dynamic
    and saved dynamic are the first copy's.
    """
    scenario = uk_scenario
    copy_ids = [
        _store_policy(
            owner_engine,
            scenario,
            scenario.parameter_value(UK_TAX_RATE, value=tax_rate),
            scenario.parameter_value(UK_OBR_SWITCH, value=False),
        )
        for tax_rate in (0.21, 0.22)
    ]
    user_id = _store_user(owner_engine, scenario)
    for copy_id in copy_ids:
        _store_saved_policy(
            owner_engine, scenario, user_id=user_id, policy_id=copy_id, name=None
        )

    listed = _service(split_role_engine, read_only=True).list_policy_copy_splits()
    applied = list(_service(split_role_engine).split_policy_copies())

    def created_rows(split: PolicyCopySplit) -> tuple[bool, bool, list[bool]]:
        return (
            split.policy.created,
            split.dynamic.created,
            [saved.saved_dynamic_created for saved in split.saved_policies],
        )

    assert [created_rows(_result_for(listed, copy_id)) for copy_id in copy_ids] == [
        (True, True, [True]),
        (True, False, [False]),
    ]
    assert [created_rows(_result_for(applied, copy_id)) for copy_id in copy_ids] == [
        created_rows(_result_for(listed, copy_id)) for copy_id in copy_ids
    ]
    assert len(_saved_dynamics(owner_engine, user_id)) == 1


def test_the_listing_s_sessions_refuse_writes(disposable_v2_database_url: str) -> None:
    with (
        unpooled_v2_read_only_sessions(disposable_v2_database_url) as sessions,
        sessions() as session,
    ):
        session.add(User(user_type="unauthenticated"))
        with pytest.raises(DBAPIError, match="read-only transaction"):
            session.flush()
