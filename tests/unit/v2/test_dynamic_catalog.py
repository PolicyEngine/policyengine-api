"""Binding dynamics and policies to a catalog, and keeping their parameters apart.

A dynamic holds only parameters under ``gov.simulation.`` (plus the US's
``simulation.``), and a policy holds none of them; each is refused with the
parameter names it may not set.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session, create_engine

from policyengine_api.data.v2.catalog.catalog_selection_validation import (
    MetadataCatalogUnavailableError,
)
from policyengine_api.data.v2.models import (
    V2_METADATA,
    Parameter,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)
from policyengine_api.services.v2.dynamics.database_session import (
    DynamicDatabaseSession,
)
from policyengine_api.services.v2.dynamics.services import (
    V2DynamicService,
    resolve_dynamic_creation_input,
)
from policyengine_api.services.v2.dynamics.types import (
    DynamicCreationInput,
    NativeDynamicCreationInput,
    ResolvedDynamicCreationInput,
)
from policyengine_api.services.v2.dynamics.validators import (
    DynamicSetsPolicyParametersError,
    DynamicStorageError,
)
from policyengine_api.services.v2.policies.services import (
    resolve_policy_creation_input,
)
from policyengine_api.services.v2.policies.types import PolicyCreationInput
from policyengine_api.services.v2.policies.validators import (
    PolicyCatalogValidationError,
    PolicySetsDynamicParametersError,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

INCOME_ELASTICITY = "gov.simulation.labor_supply_responses.elasticities.income"
MARGINAL_TAX_RATE_DELTA = "simulation.marginal_tax_rate_delta"
TAX_RATE = "gov.irs.income.rate"
RUNNING_VERSION = "5.2.0"


class Catalog:
    """A US catalog version with two dynamic parameters and one policy parameter."""

    def __init__(self, session: Session) -> None:
        self.model = TaxBenefitModel(name="policyengine-us")
        self.version = TaxBenefitModelVersion(
            model=self.model,
            version=RUNNING_VERSION,
            current_law_id=1,
            metadata_time_periods=[2026],
        )
        self.parameter_ids = {}
        for name in (INCOME_ELASTICITY, MARGINAL_TAX_RATE_DELTA, TAX_RATE):
            parameter = Parameter(name=name, tax_benefit_model_version=self.version)
            session.add(parameter)
            self.parameter_ids[name] = parameter.id
        session.commit()


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    V2_METADATA.create_all(engine)
    database_session = Session(engine)
    try:
        yield database_session
    finally:
        database_session.close()
        engine.dispose()


@pytest.fixture
def catalog(session: Session) -> Catalog:
    return Catalog(session)


def _values(catalog: Catalog, *names: str) -> list[dict[str, object]]:
    return [
        {
            "parameter_id": catalog.parameter_ids[name],
            "value": 0.25,
            "start_date": "2026-01-01T00:00:00Z",
        }
        for name in names
    ]


def _dynamic_input(catalog: Catalog, *names: str) -> DynamicCreationInput:
    return DynamicCreationInput(
        country_id="us",
        tax_benefit_model_id=catalog.model.id,
        parameter_values=_values(catalog, *names),
    )


def test_a_dynamic_is_bound_to_the_running_catalog_version(
    session: Session, catalog: Catalog
) -> None:
    resolved = resolve_dynamic_creation_input(
        session,
        _dynamic_input(catalog, INCOME_ELASTICITY, MARGINAL_TAX_RATE_DELTA),
        running_policyengine_version=RUNNING_VERSION,
    )

    assert isinstance(resolved, ResolvedDynamicCreationInput)
    assert resolved.tax_benefit_model_version_id == catalog.version.id
    assert resolved.policyengine_version == RUNNING_VERSION
    assert {value.parameter_id for value in resolved.parameter_values} == {
        catalog.parameter_ids[INCOME_ELASTICITY],
        catalog.parameter_ids[MARGINAL_TAX_RATE_DELTA],
    }


def test_a_dynamic_setting_policy_parameters_is_refused_naming_them(
    session: Session, catalog: Catalog
) -> None:
    with pytest.raises(DynamicSetsPolicyParametersError) as refusal:
        resolve_dynamic_creation_input(
            session,
            _dynamic_input(catalog, INCOME_ELASTICITY, TAX_RATE),
            running_policyengine_version=RUNNING_VERSION,
        )

    assert refusal.value.parameter_names == (TAX_RATE,)
    assert TAX_RATE in str(refusal.value)
    assert "/v2/policies" in str(refusal.value)


def test_a_dynamic_with_a_parameter_of_another_catalog_is_refused(
    session: Session, catalog: Catalog
) -> None:
    dynamic_input = DynamicCreationInput(
        country_id="us",
        tax_benefit_model_id=catalog.model.id,
        parameter_values=[
            {
                "parameter_id": UUID(int=7),
                "value": 0.25,
                "start_date": "2026-01-01T00:00:00Z",
            }
        ],
    )

    with pytest.raises(PolicyCatalogValidationError, match="every parameter_id"):
        resolve_dynamic_creation_input(
            session, dynamic_input, running_policyengine_version=RUNNING_VERSION
        )


@pytest.mark.parametrize(
    "dynamic_type", [DynamicCreationInput, ResolvedDynamicCreationInput]
)
def test_a_dynamic_with_no_values_is_refused(dynamic_type: type) -> None:
    fields: dict[str, object] = {
        "country_id": "us",
        "tax_benefit_model_id": UUID(int=1),
        "parameter_values": [],
    }
    if dynamic_type is ResolvedDynamicCreationInput:
        fields |= {
            "tax_benefit_model_version_id": UUID(int=2),
            "policyengine_version": RUNNING_VERSION,
        }

    with pytest.raises(ValidationError, match="at least 1 item"):
        dynamic_type(**fields)


def test_a_policy_setting_dynamic_parameters_is_refused_naming_them(
    session: Session, catalog: Catalog
) -> None:
    policy_input = PolicyCreationInput(
        country_id="us",
        tax_benefit_model_id=catalog.model.id,
        parameter_values=_values(
            catalog, TAX_RATE, MARGINAL_TAX_RATE_DELTA, INCOME_ELASTICITY
        ),
    )

    with pytest.raises(PolicySetsDynamicParametersError) as refusal:
        resolve_policy_creation_input(
            session, policy_input, running_policyengine_version=RUNNING_VERSION
        )

    assert refusal.value.parameter_names == (
        INCOME_ELASTICITY,
        MARGINAL_TAX_RATE_DELTA,
    )
    assert "/v2/dynamics" in str(refusal.value)


def test_a_policy_without_dynamic_parameters_is_still_bound(
    session: Session, catalog: Catalog
) -> None:
    resolved = resolve_policy_creation_input(
        session,
        PolicyCreationInput(
            country_id="us",
            tax_benefit_model_id=catalog.model.id,
            parameter_values=_values(catalog, TAX_RATE),
        ),
        running_policyengine_version=RUNNING_VERSION,
    )

    assert resolved.tax_benefit_model_version_id == catalog.version.id
    assert [value.parameter_id for value in resolved.parameter_values] == [
        catalog.parameter_ids[TAX_RATE]
    ]


def test_a_dynamic_storage_that_cannot_be_read_is_a_storage_error() -> None:
    # A database without the v2 tables fails every read with OperationalError.
    # A create's first read is the catalog query, which reports its own error.
    engine = create_engine("sqlite://")
    service = V2DynamicService(
        DynamicDatabaseSession(sessionmaker(engine, class_=Session)),
        running_policyengine_version=RUNNING_VERSION,
    )
    try:
        with pytest.raises(DynamicStorageError) as failure:
            service.get_dynamic(country_id="us", dynamic_id=UUID(int=3))
        with pytest.raises(MetadataCatalogUnavailableError):
            service.create_dynamic(
                NativeDynamicCreationInput(
                    country_id="us",
                    tax_benefit_model_id=UUID(int=1),
                    parameter_values=[
                        {
                            "parameter_id": UUID(int=2),
                            "value": 0.25,
                            "start_date": "2026-01-01T00:00:00Z",
                        }
                    ],
                )
            )
    finally:
        engine.dispose()

    assert isinstance(failure.value.__cause__, OperationalError)
