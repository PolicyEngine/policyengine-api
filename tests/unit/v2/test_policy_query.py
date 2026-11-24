"""Country-scoped complete policy read tests."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

import pytest

from policyengine_api.data.v2.models import (
    Parameter,
    ParameterValue,
    Policy,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)
from policyengine_api.services.v2.policies.services import (
    read_complete_policy,
    read_policy_page,
)
from policyengine_api.services.v2.policies.validators import (
    PolicyNotFoundError,
)
from tests.fixtures.database_sessions import sqlite_v2_sessions

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlmodel import Session


@contextmanager
def _stored_policies() -> Iterator[
    tuple[Session, TaxBenefitModel, Policy, Policy, Policy]
]:
    """Yield a Session of a database storing three policies, the model and them."""
    with sqlite_v2_sessions() as sessions, sessions(expire_on_commit=True) as session:
        yield (session, *_store_policies(session))


def _store_policies(session: Session) -> tuple[TaxBenefitModel, Policy, Policy, Policy]:
    """Store a model's two US policies and a UK policy; return the model and them."""
    model = TaxBenefitModel(name="policyengine-us")
    version = TaxBenefitModelVersion(
        model=model,
        version="5.2.0",
        current_law_id=1,
        metadata_time_periods=[2026],
    )
    alpha = Parameter(name="gov.alpha", tax_benefit_model_version=version)
    zeta = Parameter(name="gov.zeta", tax_benefit_model_version=version)
    created = datetime(2026, 1, 1, tzinfo=UTC)
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
    return model, first, second, other_country


def test_detail_joins_parameter_names_and_orders_complete_values() -> None:
    with _stored_policies() as (session, _model, first, _second, _other):
        result = read_complete_policy(session, country_id="us", policy_id=first.id)

        assert result.id == first.id
        assert result.created_at == first.created_at
        assert [value.parameter_name for value in result.parameter_values] == [
            "gov.alpha",
            "gov.alpha",
            "gov.zeta",
        ]
        assert [value.value for value in result.parameter_values] == [0, 1, 2]


def test_detail_uses_country_as_part_of_resource_identity() -> None:
    with (
        _stored_policies() as (session, _model, first, _second, _other),
        pytest.raises(PolicyNotFoundError),
    ):
        read_complete_policy(session, country_id="uk", policy_id=first.id)


def test_empty_policy_has_an_empty_nested_collection() -> None:
    with _stored_policies() as (session, _model, _first, second, _other):
        assert (
            read_complete_policy(
                session,
                country_id="us",
                policy_id=second.id,
            ).parameter_values
            == ()
        )


def test_collection_filters_orders_paginates_and_returns_complete_items() -> None:
    with _stored_policies() as (session, model, first, second, _other):
        first_page = read_policy_page(
            session,
            country_id="us",
            tax_benefit_model_id=model.id,
            offset=0,
            limit=1,
        )
        second_page = read_policy_page(
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


def test_model_filter_is_exact() -> None:
    with _stored_policies() as (session, _model, _first, _second, _other):
        result = read_policy_page(
            session,
            country_id="us",
            tax_benefit_model_id=UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
            offset=0,
            limit=100,
        )
        assert result.items == ()
        assert result.has_more is False
