"""PostgreSQL tests for dynamics, created by ``/v2/dynamics`` and the v1-to-v2 copy.

The services run as API v1's runtime role, which proves its declared
privileges cover them (rule ``api.v2.runtime-privileges-tested-as-runtime-role``);
the catalog is written and everything removed as the superuser.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, or_, select

from policyengine_api.data.v2.models import (
    Dynamic,
    LegacyPolicyMapping,
    Parameter,
    ParameterValue,
    Policy,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)
from policyengine_api.services.v2.dynamics.database_session import (
    DynamicDatabaseSession,
)
from policyengine_api.services.v2.dynamics.services import V2DynamicService
from policyengine_api.services.v2.dynamics.types import NativeDynamicCreationInput
from policyengine_api.services.v2.dynamics.validators import DynamicNotFoundError
from policyengine_api.services.v2.policies.database_session import (
    PolicyDatabaseSession,
)
from policyengine_api.services.v2.policies.services import V2PolicyService
from policyengine_api.services.v2.policies.types import LegacyPolicySnapshot

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

    from tests.integration.conftest import ManagedV2Roles

RUNNING_VERSION = "5.2.0"
US_INCOME_ELASTICITY = "gov.simulation.labor_supply_responses.elasticities.income"
US_MTR_DELTA = "simulation.marginal_tax_rate_delta"
US_TAX_RATE = "gov.irs.income.rate"
UK_INCOME_ELASTICITY = "gov.simulation.labour_supply_responses.income_elasticity"
UK_OLD_INCOME_ELASTICITY = "gov.simulation.labor_supply_responses.income_elasticity"
UK_TAX_RATE = "gov.hmrc.income_tax.rate"


@dataclass(frozen=True)
class StoredCatalog:
    """A country's running catalog version and its parameters' IDs by name."""

    model_id: UUID
    version_id: UUID
    parameter_ids: dict[str, UUID]


def _store_catalog(
    session: Session, country_id: str, names: list[str]
) -> StoredCatalog:
    model = TaxBenefitModel(name=f"policyengine-{country_id}")
    version = TaxBenefitModelVersion(
        model=model,
        version=RUNNING_VERSION,
        current_law_id=1,
        metadata_time_periods=[2026],
    )
    parameters = [
        Parameter(name=name, tax_benefit_model_version=version) for name in names
    ]
    session.add_all(parameters)
    session.flush()
    return StoredCatalog(
        model_id=model.id,
        version_id=version.id,
        parameter_ids={parameter.name: parameter.id for parameter in parameters},
    )


def _remove_catalog(
    v2_owner_sessions: sessionmaker[Session], catalog: StoredCatalog
) -> None:
    with v2_owner_sessions.begin() as session:
        dynamic_ids = select(Dynamic.id).where(
            Dynamic.tax_benefit_model_id == catalog.model_id
        )
        policy_ids = select(Policy.id).where(
            Policy.tax_benefit_model_id == catalog.model_id
        )
        session.execute(
            delete(LegacyPolicyMapping).where(
                or_(
                    LegacyPolicyMapping.policy_id.in_(policy_ids),
                    LegacyPolicyMapping.dynamic_id.in_(dynamic_ids),
                )
            )
        )
        session.execute(
            delete(ParameterValue).where(
                or_(
                    ParameterValue.policy_id.in_(policy_ids),
                    ParameterValue.dynamic_id.in_(dynamic_ids),
                )
            )
        )
        session.execute(
            delete(Dynamic).where(Dynamic.tax_benefit_model_id == catalog.model_id)
        )
        session.execute(
            delete(Policy).where(Policy.tax_benefit_model_id == catalog.model_id)
        )
        session.execute(
            delete(Parameter).where(
                Parameter.tax_benefit_model_version_id == catalog.version_id
            )
        )
        session.execute(
            delete(TaxBenefitModelVersion).where(
                TaxBenefitModelVersion.id == catalog.version_id
            )
        )
        session.execute(
            delete(TaxBenefitModel).where(TaxBenefitModel.id == catalog.model_id)
        )


@pytest.fixture
def runtime_sessions(
    managed_v2_roles: ManagedV2Roles,
    v2_sessions_as_role: Callable[[str], sessionmaker[Session]],
) -> sessionmaker[Session]:
    """Open sessions as API v1's runtime role."""
    return v2_sessions_as_role(managed_v2_roles.runtime)


@pytest.fixture
def us_catalog(v2_owner_sessions: sessionmaker[Session]) -> Iterator[StoredCatalog]:
    with v2_owner_sessions.begin() as session:
        catalog = _store_catalog(
            session, "us", [US_INCOME_ELASTICITY, US_MTR_DELTA, US_TAX_RATE]
        )
    try:
        yield catalog
    finally:
        _remove_catalog(v2_owner_sessions, catalog)


@pytest.fixture
def uk_catalog(v2_owner_sessions: sessionmaker[Session]) -> Iterator[StoredCatalog]:
    with v2_owner_sessions.begin() as session:
        catalog = _store_catalog(session, "uk", [UK_INCOME_ELASTICITY, UK_TAX_RATE])
    try:
        yield catalog
    finally:
        _remove_catalog(v2_owner_sessions, catalog)


def _dynamic_service(sessions: sessionmaker[Session]) -> V2DynamicService:
    return V2DynamicService(
        DynamicDatabaseSession(sessions),
        running_policyengine_version=RUNNING_VERSION,
    )


def _policy_service(sessions: sessionmaker[Session]) -> V2PolicyService:
    return V2PolicyService(
        PolicyDatabaseSession(sessions),
        running_policyengine_version=RUNNING_VERSION,
    )


def _dynamic_input(catalog: StoredCatalog, value: float) -> NativeDynamicCreationInput:
    return NativeDynamicCreationInput(
        country_id="us",
        tax_benefit_model_id=catalog.model_id,
        parameter_values=[
            {
                "parameter_id": catalog.parameter_ids[US_INCOME_ELASTICITY],
                "value": value,
                "start_date": "2026-01-01T00:00:00Z",
            },
            {
                "parameter_id": catalog.parameter_ids[US_MTR_DELTA],
                "value": 500,
                "start_date": "2026-01-01T00:00:00Z",
            },
        ],
    )


def _snapshot(
    country_id: str, legacy_policy_id: int, policy_json: dict[str, object]
) -> LegacyPolicySnapshot:
    return LegacyPolicySnapshot(
        country_id=country_id,
        legacy_policy_id=legacy_policy_id,
        label=None,
        api_version="1.0.0",
        policy_json=policy_json,
        source_policy_hash=f"v1-hash-{legacy_policy_id}",
    )


def _stored_names(session: Session, *, policy_id=None, dynamic_id=None) -> set[str]:
    owner = (
        ParameterValue.policy_id == policy_id
        if policy_id is not None
        else ParameterValue.dynamic_id == dynamic_id
    )
    return set(
        session.scalars(
            select(Parameter.name)
            .join(ParameterValue, ParameterValue.parameter_id == Parameter.id)
            .where(owner)
        )
    )


def test_identical_dynamic_content_is_stored_once_and_read_back(
    runtime_sessions, us_catalog, v2_owner_sessions
) -> None:
    service = _dynamic_service(runtime_sessions)

    created = service.create_dynamic(_dynamic_input(us_catalog, 0.25))
    found = service.create_dynamic(_dynamic_input(us_catalog, 0.25))
    other = service.create_dynamic(_dynamic_input(us_catalog, 0.5))
    read = service.get_dynamic(country_id="us", dynamic_id=created.item.id)

    assert created.created is True
    assert found.created is False
    assert found.item.id == created.item.id
    assert other.created is True
    assert other.item.id != created.item.id
    assert read.tax_benefit_model_version_id == us_catalog.version_id
    assert read.missing_parameters == ()
    assert {(value.parameter_name, value.value) for value in read.parameter_values} == {
        (US_INCOME_ELASTICITY, 0.25),
        (US_MTR_DELTA, 500),
    }
    with v2_owner_sessions() as session:
        stored = session.scalars(
            select(Dynamic).where(Dynamic.tax_benefit_model_id == us_catalog.model_id)
        ).all()
        assert len(stored) == 2
        assert _stored_names(session, dynamic_id=created.item.id) == {
            US_INCOME_ELASTICITY,
            US_MTR_DELTA,
        }


def test_a_dynamic_is_read_only_in_its_own_country(
    runtime_sessions, us_catalog
) -> None:
    service = _dynamic_service(runtime_sessions)
    created = service.create_dynamic(_dynamic_input(us_catalog, 0.25))

    with pytest.raises(DynamicNotFoundError):
        service.get_dynamic(country_id="uk", dynamic_id=created.item.id)
    with pytest.raises(DynamicNotFoundError):
        service.get_dynamic(country_id="us", dynamic_id=uuid4())


def test_the_copy_splits_a_us_policy_into_a_policy_and_a_dynamic(
    runtime_sessions, us_catalog, v2_owner_sessions
) -> None:
    service = _policy_service(runtime_sessions)
    snapshot = _snapshot(
        "us",
        9101,
        {
            US_TAX_RATE: {"2026": 0.2},
            US_INCOME_ELASTICITY: {"2026": 0.25},
            US_MTR_DELTA: {"2026": 500},
        },
    )

    first = service.mirror_legacy_policy(snapshot)
    retry = service.mirror_legacy_policy(snapshot)

    assert first.policy_created is True
    assert first.dynamic_created is True
    assert first.dynamic_id is not None
    assert retry.policy_id == first.policy_id
    assert retry.dynamic_id == first.dynamic_id
    assert retry.mapping_created is False
    with v2_owner_sessions() as session:
        assert _stored_names(session, policy_id=first.policy_id) == {US_TAX_RATE}
        assert _stored_names(session, dynamic_id=first.dynamic_id) == {
            US_INCOME_ELASTICITY,
            US_MTR_DELTA,
        }
        mapping = session.scalars(
            select(LegacyPolicyMapping).where(
                LegacyPolicyMapping.country_id == "us",
                LegacyPolicyMapping.legacy_policy_id == 9101,
            )
        ).one()
        assert (mapping.policy_id, mapping.dynamic_id) == (
            first.policy_id,
            first.dynamic_id,
        )


def test_the_copy_rewrites_the_uk_old_spelling_into_the_dynamic(
    runtime_sessions, uk_catalog, v2_owner_sessions
) -> None:
    service = _policy_service(runtime_sessions)
    dynamic_values_only = service.mirror_legacy_policy(
        _snapshot("uk", 9201, {UK_OLD_INCOME_ELASTICITY: {"2026": 0.3}})
    )
    same_values_new_spelling = service.mirror_legacy_policy(
        _snapshot("uk", 9202, {UK_INCOME_ELASTICITY: {"2026": 0.3}})
    )
    no_dynamic_values = service.mirror_legacy_policy(
        _snapshot("uk", 9203, {UK_TAX_RATE: {"2026": 0.4}})
    )

    assert dynamic_values_only.dynamic_id is not None
    assert same_values_new_spelling.dynamic_id == dynamic_values_only.dynamic_id
    assert same_values_new_spelling.dynamic_created is False
    assert no_dynamic_values.dynamic_id is None
    assert no_dynamic_values.dynamic_created is False
    with v2_owner_sessions() as session:
        # A v1 policy holding only dynamic values maps to an empty policy.
        assert _stored_names(session, policy_id=dynamic_values_only.policy_id) == set()
        assert _stored_names(session, dynamic_id=dynamic_values_only.dynamic_id) == {
            UK_INCOME_ELASTICITY
        }
        dynamic = session.get(Dynamic, dynamic_values_only.dynamic_id)
        assert dynamic is not None
        assert dynamic.country_id == "uk"
        assert dynamic.tax_benefit_model_version_id == uk_catalog.version_id


def test_a_copy_made_before_the_split_keeps_its_mapping_without_a_dynamic(
    runtime_sessions, us_catalog, v2_owner_sessions
) -> None:
    snapshot = _snapshot("us", 9301, {US_INCOME_ELASTICITY: {"2026": 0.25}})
    with v2_owner_sessions.begin() as session:
        earlier_copy = Policy(
            country_id="us",
            tax_benefit_model_id=us_catalog.model_id,
            tax_benefit_model_version_id=us_catalog.version_id,
            canonicalization_version=1,
            content_hash=uuid4().hex * 2,
        )
        session.add(earlier_copy)
        session.flush()
        earlier_copy_id = earlier_copy.id
        session.add(
            LegacyPolicyMapping(
                country_id="us",
                legacy_policy_id=9301,
                policy_id=earlier_copy_id,
                source_policy_hash=snapshot.source_policy_hash,
            )
        )

    result = _policy_service(runtime_sessions).mirror_legacy_policy(snapshot)

    assert result.policy_id == earlier_copy_id
    assert result.dynamic_id is None
    assert result.mapping_created is False
