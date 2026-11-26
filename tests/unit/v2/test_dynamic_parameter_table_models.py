"""Dynamic parameters and their values have tables of their own (C1 · 50).

``dynamic_parameters`` has ``parameters``' columns, IDs and unique name per
catalog version. ``dynamic_parameter_values`` holds their current-law values
(no dynamic) and every dynamic's values, with no policy: one current-law value
per parameter and start date, and one per dynamic, parameter and start date.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session, select

from policyengine_api.data.v2.models import (
    Dynamic,
    DynamicParameter,
    DynamicParameterValue,
    Parameter,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)
from tests.fixtures.database_sessions import sqlite_v2_sessions
from tests.fixtures.v2_countries import add_listed_countries
from tests.unit.v2.v2_schema_reading import (
    declared_index,
    model_columns,
    stored_v2_table,
)

START_DATE = datetime(2026, 1, 1, tzinfo=UTC)
ELASTICITY = "gov.simulation.labor_supply_responses.elasticities.income"


@contextmanager
def _sqlite_sessions_with_foreign_keys() -> Iterator[sessionmaker[Session]]:
    with sqlite_v2_sessions(foreign_keys=True) as sessions:
        with sessions(expire_on_commit=True) as session:
            add_listed_countries(session)
        yield sessions


def _catalog(
    session: Session,
) -> tuple[TaxBenefitModel, TaxBenefitModelVersion, DynamicParameter]:
    model = TaxBenefitModel(name="policyengine-us")
    version = TaxBenefitModelVersion(
        model=model, version="2.2.2", current_law_id=1, metadata_time_periods=[2026]
    )
    parameter = DynamicParameter(name=ELASTICITY, tax_benefit_model_version=version)
    session.add_all([model, version, parameter])
    session.commit()
    return model, version, parameter


def _dynamic(
    session: Session, model: TaxBenefitModel, version: TaxBenefitModelVersion
) -> Dynamic:
    dynamic = Dynamic(
        country_id="us",
        tax_benefit_model_id=model.id,
        tax_benefit_model_version_id=version.id,
        canonicalization_version=1,
        content_hash="d" * 64,
    )
    session.add(dynamic)
    session.commit()
    return dynamic


def test_dynamic_parameters_have_policy_parameters_columns_and_name_rule() -> None:
    dynamic_parameters = stored_v2_table("dynamic_parameters")

    assert {
        name: (str(column.type), column.nullable)
        for name, column in dynamic_parameters.columns.items()
    } == {
        name: (str(column.type), column.nullable)
        for name, column in stored_v2_table("parameters").columns.items()
    }
    assert dynamic_parameters.unique_constraints == {
        "uq_dynamic_parameters_model_version_name": (
            "tax_benefit_model_version_id",
            "name",
        )
    }
    assert dynamic_parameters.references_by_column == {
        "tax_benefit_model_version_id": ("tax_benefit_model_versions", "CASCADE"),
    }


def test_dynamic_parameter_values_name_a_dynamic_parameter_and_no_policy() -> None:
    values = stored_v2_table("dynamic_parameter_values")
    columns = model_columns("dynamic_parameter_values")

    assert set(values.columns) == {
        "id",
        "created_at",
        "dynamic_parameter_id",
        "value_json",
        "start_date",
        "end_date",
        "dynamic_id",
    }
    assert not columns.dynamic_parameter_id.nullable
    assert columns.dynamic_id.nullable
    assert columns.end_date.nullable
    assert values.references_by_column == {
        "dynamic_parameter_id": ("dynamic_parameters", "CASCADE"),
        "dynamic_id": ("dynamics", "CASCADE"),
    }
    assert set(values.checks) == {"ck_dynamic_parameter_values_effective_period"}
    assert values.index_columns["ix_dynamic_parameter_values_parameter_period"] == (
        "dynamic_parameter_id",
        "start_date",
        "end_date",
    )


@pytest.mark.parametrize(
    ("index_name", "columns", "condition"),
    [
        (
            "uq_dynamic_parameter_values_current_law_parameter_start_date",
            ("dynamic_parameter_id", "start_date"),
            "dynamic_id IS NULL",
        ),
        (
            "uq_dynamic_parameter_values_dynamic_parameter_start_date",
            ("dynamic_id", "dynamic_parameter_id", "start_date"),
            "dynamic_id IS NOT NULL",
        ),
    ],
)
def test_values_are_unique_per_owner_parameter_and_start_date_in_both_dialects(
    index_name: str, columns: tuple[str, ...], condition: str
) -> None:
    index = declared_index(DynamicParameterValue, index_name)

    assert index.unique
    assert tuple(column.name for column in index.columns) == columns
    assert str(index.dialect_options["postgresql"]["where"]) == condition
    assert str(index.dialect_options["sqlite"]["where"]) == condition


def test_a_dynamic_s_value_must_name_a_dynamic_parameter() -> None:
    with (
        _sqlite_sessions_with_foreign_keys() as sessions,
        sessions(expire_on_commit=True) as session,
    ):
        model, version, _parameter = _catalog(session)
        policy_parameter = Parameter(
            name="gov.irs.rate", tax_benefit_model_version=version
        )
        session.add(policy_parameter)
        session.commit()
        dynamic = _dynamic(session, model, version)
        session.add(
            DynamicParameterValue(
                dynamic_parameter_id=policy_parameter.id,
                dynamic_id=dynamic.id,
                value_json=0.1,
                start_date=START_DATE,
            )
        )
        with pytest.raises(IntegrityError, match="FOREIGN KEY constraint failed"):
            session.commit()


def test_one_current_law_value_and_one_value_per_dynamic_for_each_start_date() -> None:
    with (
        _sqlite_sessions_with_foreign_keys() as sessions,
        sessions(expire_on_commit=True) as session,
    ):
        model, version, parameter = _catalog(session)
        dynamic = _dynamic(session, model, version)
        session.add_all(
            [
                DynamicParameterValue(
                    dynamic_parameter_id=parameter.id,
                    value_json=0.1,
                    start_date=START_DATE,
                ),
                DynamicParameterValue(
                    dynamic_parameter_id=parameter.id,
                    dynamic_id=dynamic.id,
                    value_json=0.2,
                    start_date=START_DATE,
                ),
            ]
        )
        session.commit()
        for owner in (None, dynamic.id):
            session.add(
                DynamicParameterValue(
                    dynamic_parameter_id=parameter.id,
                    dynamic_id=owner,
                    value_json=0.3,
                    start_date=START_DATE,
                )
            )
            with pytest.raises(IntegrityError, match="UNIQUE constraint failed"):
                session.commit()
            session.rollback()


def test_a_dynamic_lists_its_values_and_deleting_it_deletes_them() -> None:
    with (
        _sqlite_sessions_with_foreign_keys() as sessions,
        sessions(expire_on_commit=True) as session,
    ):
        model, version, parameter = _catalog(session)
        dynamic = _dynamic(session, model, version)
        value = DynamicParameterValue(
            dynamic_parameter_id=parameter.id,
            dynamic_id=dynamic.id,
            value_json=0.2,
            start_date=START_DATE,
        )
        session.add(value)
        session.commit()

        assert [stored.id for stored in dynamic.parameter_values] == [value.id]
        assert [stored.id for stored in parameter.values] == [value.id]
        session.delete(dynamic)
        session.commit()
        assert session.exec(select(DynamicParameterValue)).all() == []
        assert session.get(DynamicParameter, parameter.id) is not None
