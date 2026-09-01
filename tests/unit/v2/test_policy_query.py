"""Country-scoped complete policy read tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlmodel import Session, create_engine
import pytest

from policyengine_api.data.v2.models import (
    Parameter,
    ParameterValue,
    Policy,
    TaxBenefitModel,
    TaxBenefitModelVersion,
    V2_METADATA,
)
from policyengine_api.data.v2.policies.queries import (
    PolicyNotFoundError,
    list_policies,
    read_policy,
)


def _stored_policies():
    engine = create_engine("sqlite://")
    V2_METADATA.create_all(engine)
    session = Session(engine)
    model = TaxBenefitModel(name="policyengine-us")
    version = TaxBenefitModelVersion(
        model=model,
        version="5.2.0",
        current_law_id=1,
        metadata_time_periods=[2026],
    )
    alpha = Parameter(name="gov.alpha", tax_benefit_model_version=version)
    zeta = Parameter(name="gov.zeta", tax_benefit_model_version=version)
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first = Policy(
        id=UUID("00000000-0000-0000-0000-000000000010"),
        country_id="us",
        tax_benefit_model=model,
        tax_benefit_model_version=version,
        canonicalization_version=1,
        content_hash="1" * 64,
        created_at=created,
        updated_at=created,
    )
    second = Policy(
        id=UUID("00000000-0000-0000-0000-000000000020"),
        country_id="us",
        tax_benefit_model=model,
        tax_benefit_model_version=version,
        canonicalization_version=1,
        content_hash="2" * 64,
        created_at=created + timedelta(seconds=1),
        updated_at=created + timedelta(seconds=1),
    )
    other_country = Policy(
        id=UUID("00000000-0000-0000-0000-000000000030"),
        country_id="uk",
        tax_benefit_model=model,
        tax_benefit_model_version=version,
        canonicalization_version=1,
        content_hash="3" * 64,
        created_at=created + timedelta(seconds=2),
        updated_at=created + timedelta(seconds=2),
    )
    session.add_all(
        [
            first,
            second,
            other_country,
            ParameterValue(
                id=UUID("00000000-0000-0000-0000-000000000200"),
                policy=first,
                parameter=zeta,
                value_json=2,
                start_date=created,
            ),
            ParameterValue(
                id=UUID("00000000-0000-0000-0000-000000000100"),
                policy=first,
                parameter=alpha,
                value_json=1,
                start_date=created + timedelta(days=1),
            ),
            ParameterValue(
                id=UUID("00000000-0000-0000-0000-000000000090"),
                policy=first,
                parameter=alpha,
                value_json=0,
                start_date=created,
            ),
        ]
    )
    session.commit()
    return engine, session, model, first, second, other_country


def test_detail_joins_parameter_names_and_orders_complete_values() -> None:
    engine, session, _model, first, _second, _other = _stored_policies()
    try:
        result = read_policy(session, country_id="us", policy_id=first.id)

        assert result.id == first.id
        assert result.created_at == first.created_at
        assert [value.parameter_name for value in result.parameter_values] == [
            "gov.alpha",
            "gov.alpha",
            "gov.zeta",
        ]
        assert [value.value for value in result.parameter_values] == [0, 1, 2]
    finally:
        session.close()
        engine.dispose()


def test_detail_uses_country_as_part_of_resource_identity() -> None:
    engine, session, _model, first, _second, _other = _stored_policies()
    try:
        with pytest.raises(PolicyNotFoundError):
            read_policy(session, country_id="uk", policy_id=first.id)
    finally:
        session.close()
        engine.dispose()


def test_empty_policy_has_an_empty_nested_collection() -> None:
    engine, session, _model, _first, second, _other = _stored_policies()
    try:
        assert (
            read_policy(
                session,
                country_id="us",
                policy_id=second.id,
            ).parameter_values
            == ()
        )
    finally:
        session.close()
        engine.dispose()


def test_collection_filters_orders_paginates_and_returns_complete_items() -> None:
    engine, session, model, first, second, _other = _stored_policies()
    try:
        first_page = list_policies(
            session,
            country_id="us",
            tax_benefit_model_id=model.id,
            offset=0,
            limit=1,
        )
        second_page = list_policies(
            session,
            country_id="us",
            tax_benefit_model_id=model.id,
            offset=1,
            limit=1,
        )

        assert [item.id for item in first_page.items] == [first.id]
        assert len(first_page.items[0].parameter_values) == 3
        assert first_page.has_more is True
        assert (first_page.offset, first_page.limit) == (0, 1)
        assert [item.id for item in second_page.items] == [second.id]
        assert second_page.has_more is False
        assert all(item.country_id == "us" for item in first_page.items)
    finally:
        session.close()
        engine.dispose()


def test_model_filter_is_exact() -> None:
    engine, session, _model, _first, _second, _other = _stored_policies()
    try:
        result = list_policies(
            session,
            country_id="us",
            tax_benefit_model_id=UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
        )
        assert result.items == ()
        assert result.has_more is False
    finally:
        session.close()
        engine.dispose()
