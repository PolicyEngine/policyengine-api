"""Exact catalog-binding tests for immutable policies."""

from __future__ import annotations

from uuid import uuid4

from sqlmodel import Session, create_engine
import pytest

from policyengine_api.data.v2.catalog.catalog_selection import (
    MetadataCatalogVersionNotFoundError,
)
from policyengine_api.data.v2.models import (
    Parameter,
    TaxBenefitModel,
    TaxBenefitModelVersion,
    V2_METADATA,
)
from policyengine_api.data.v2.policies.catalog_repository import (
    PolicyCatalogValidationError,
    resolve_policy_catalog,
)
from policyengine_api.services.v2.policies.commands import PolicyCreateCommand


def _catalog_session():
    engine = create_engine("sqlite://")
    V2_METADATA.create_all(engine)
    session = Session(engine)
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
    return engine, session, us_model, current, current_parameter, previous_parameter


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
    return PolicyCreateCommand(
        country_id=country_id,
        tax_benefit_model_id=model_id,
        parameter_values=parameter_values,
    )


def test_resolver_binds_model_version_and_all_parameter_ids() -> None:
    engine, session, model, version, parameter, _previous = _catalog_session()
    try:
        resolved = resolve_policy_catalog(
            session,
            _command(model.id, parameter.id),
            policyengine_version="5.2.0",
            running_policyengine_version="different-running-version",
        )

        assert resolved.country_id == "us"
        assert resolved.tax_benefit_model_id == model.id
        assert resolved.tax_benefit_model_version_id == version.id
        assert resolved.policyengine_version == "5.2.0"
        assert resolved.parameter_values[0].parameter_id == parameter.id
    finally:
        session.close()
        engine.dispose()


def test_omitted_version_selects_the_running_catalog() -> None:
    engine, session, model, version, _parameter, _previous = _catalog_session()
    try:
        resolved = resolve_policy_catalog(
            session,
            _command(model.id),
            running_policyengine_version="5.2.0",
        )
        assert resolved.tax_benefit_model_version_id == version.id
    finally:
        session.close()
        engine.dispose()


def test_wrong_stable_model_is_rejected() -> None:
    engine, session, _model, _version, parameter, _previous = _catalog_session()
    try:
        with pytest.raises(PolicyCatalogValidationError, match="selected country"):
            resolve_policy_catalog(
                session,
                _command(uuid4(), parameter.id),
                policyengine_version="5.2.0",
            )
    finally:
        session.close()
        engine.dispose()


def test_parameter_from_another_model_version_is_rejected() -> None:
    engine, session, model, _version, _parameter, previous = _catalog_session()
    try:
        with pytest.raises(PolicyCatalogValidationError, match="every parameter_id"):
            resolve_policy_catalog(
                session,
                _command(model.id, previous.id),
                policyengine_version="5.2.0",
            )
    finally:
        session.close()
        engine.dispose()


def test_absent_or_unsupported_catalog_never_falls_back() -> None:
    engine, session, model, _version, _parameter, _previous = _catalog_session()
    try:
        with pytest.raises(MetadataCatalogVersionNotFoundError):
            resolve_policy_catalog(
                session,
                _command(model.id),
                policyengine_version="4.0.0",
            )
        with pytest.raises(MetadataCatalogVersionNotFoundError):
            resolve_policy_catalog(
                session,
                _command(model.id, country_id="uk"),
                policyengine_version="5.2.0",
            )
    finally:
        session.close()
        engine.dispose()
