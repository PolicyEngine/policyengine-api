"""Exact catalog-binding tests for immutable policies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from policyengine_api.data.v2.catalog.catalog_selection_validation import (
    MetadataCatalogVersionNotFoundError,
)
from policyengine_api.data.v2.models import (
    Parameter,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)
from policyengine_api.services.v2.policies.services import (
    resolve_policy_creation_input,
)
from policyengine_api.services.v2.policies.types import PolicyCreationInput
from policyengine_api.services.v2.policies.validators import (
    PolicyCatalogValidationError,
)
from tests.fixtures.database_sessions import sqlite_v2_sessions

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlmodel import Session


@dataclass(frozen=True)
class StoredCatalog:
    """A US model's two stored versions, each with one parameter.

    ``session`` is open on the in-memory SQLite database that holds them.
    """

    session: Session
    model: TaxBenefitModel
    version: TaxBenefitModelVersion
    parameter: Parameter
    previous_parameter: Parameter


@pytest.fixture
def stored_catalog() -> Iterator[StoredCatalog]:
    with sqlite_v2_sessions() as sessions, sessions() as session:
        us_model = TaxBenefitModel(name="policyengine-us")
        current = TaxBenefitModelVersion(
            model=us_model,
            version="5.2.0",
            current_law_id=1,
            metadata_time_periods=[2026],
        )
        previous = TaxBenefitModelVersion(
            model=us_model,
            version="5.1.0",
            current_law_id=2,
            metadata_time_periods=[2025],
        )
        current_parameter = Parameter(
            name="gov.example.rate",
            tax_benefit_model_version=current,
        )
        previous_parameter = Parameter(
            name="gov.example.old_rate",
            tax_benefit_model_version=previous,
        )
        session.add_all([current_parameter, previous_parameter])
        session.commit()
        yield StoredCatalog(
            session=session,
            model=us_model,
            version=current,
            parameter=current_parameter,
            previous_parameter=previous_parameter,
        )


def _command(model_id, parameter_id=None, *, country_id="us"):
    parameter_values = []
    if parameter_id is not None:
        parameter_values.append(
            {
                "parameter_id": parameter_id,
                "value": 0.2,
                "start_date": "2026-01-01T00:00:00Z",
            }
        )
    return PolicyCreationInput(
        country_id=country_id,
        tax_benefit_model_id=model_id,
        parameter_values=parameter_values,
    )


def test_resolver_binds_model_version_and_all_parameter_ids(
    stored_catalog: StoredCatalog,
) -> None:
    resolved = resolve_policy_creation_input(
        stored_catalog.session,
        _command(stored_catalog.model.id, stored_catalog.parameter.id),
        policyengine_version="5.2.0",
        running_policyengine_version="different-running-version",
    )

    assert resolved.country_id == "us"
    assert resolved.tax_benefit_model_id == stored_catalog.model.id
    assert resolved.tax_benefit_model_version_id == stored_catalog.version.id
    assert resolved.policyengine_version == "5.2.0"
    assert resolved.parameter_values[0].parameter_id == stored_catalog.parameter.id


def test_omitted_version_selects_the_running_catalog(
    stored_catalog: StoredCatalog,
) -> None:
    resolved = resolve_policy_creation_input(
        stored_catalog.session,
        _command(stored_catalog.model.id),
        running_policyengine_version="5.2.0",
    )
    assert resolved.tax_benefit_model_version_id == stored_catalog.version.id


def test_wrong_stable_model_is_rejected(stored_catalog: StoredCatalog) -> None:
    with pytest.raises(PolicyCatalogValidationError, match="selected country"):
        resolve_policy_creation_input(
            stored_catalog.session,
            _command(uuid4(), stored_catalog.parameter.id),
            policyengine_version="5.2.0",
        )


def test_parameter_from_another_model_version_is_rejected(
    stored_catalog: StoredCatalog,
) -> None:
    with pytest.raises(PolicyCatalogValidationError, match="every parameter_id"):
        resolve_policy_creation_input(
            stored_catalog.session,
            _command(stored_catalog.model.id, stored_catalog.previous_parameter.id),
            policyengine_version="5.2.0",
        )


def test_absent_or_unsupported_catalog_never_falls_back(
    stored_catalog: StoredCatalog,
) -> None:
    with pytest.raises(MetadataCatalogVersionNotFoundError):
        resolve_policy_creation_input(
            stored_catalog.session,
            _command(stored_catalog.model.id),
            policyengine_version="4.0.0",
        )
    with pytest.raises(MetadataCatalogVersionNotFoundError):
        resolve_policy_creation_input(
            stored_catalog.session,
            _command(stored_catalog.model.id, country_id="uk"),
            policyengine_version="5.2.0",
        )
