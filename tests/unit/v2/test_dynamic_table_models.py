"""Dynamics are stored as policies are: once per canonical content hash."""

import subprocess
import sys
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, create_engine

from policyengine_api.data.v2.models import (
    V2_METADATA,
    Dynamic,
    LegacyPolicyMapping,
    Parameter,
    ParameterValue,
    Policy,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)
from tests.fixtures.v2_countries import add_listed_countries

START_DATE = datetime(2026, 1, 1, tzinfo=UTC)


def _sqlite_engine_with_foreign_keys() -> sa.Engine:
    engine = create_engine("sqlite://")

    @sa.event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    V2_METADATA.create_all(engine)
    with Session(engine) as session:
        add_listed_countries(session)
    return engine


def _catalog() -> tuple[TaxBenefitModel, TaxBenefitModelVersion, Parameter]:
    model = TaxBenefitModel(name="policyengine-us")
    version = TaxBenefitModelVersion(
        model=model, version="2.2.2", current_law_id=1, metadata_time_periods=[2026]
    )
    parameter = Parameter(
        name="gov.simulation.labor_supply_responses.elasticities.income",
        tax_benefit_model_version=version,
    )
    return model, version, parameter


def _dynamic(
    model: TaxBenefitModel,
    version: TaxBenefitModelVersion,
    *,
    content_hash: str = "d" * 64,
    country_id: str = "us",
) -> Dynamic:
    return Dynamic(
        country_id=country_id,
        tax_benefit_model_id=model.id,
        tax_benefit_model_version_id=version.id,
        canonicalization_version=1,
        content_hash=content_hash,
    )


def test_dynamics_have_policies_columns_and_no_name_or_description() -> None:
    dynamics = V2_METADATA.tables["dynamics"]
    policies = V2_METADATA.tables["policies"]

    assert set(dynamics.c.keys()) == set(policies.c.keys())
    assert "name" not in dynamics.c
    assert "description" not in dynamics.c
    for column_name in (
        "country_id",
        "tax_benefit_model_id",
        "tax_benefit_model_version_id",
        "canonicalization_version",
        "content_hash",
    ):
        assert not dynamics.c[column_name].nullable
    foreign_keys = {
        foreign_key.parent.name: (foreign_key.column.table.name, foreign_key.ondelete)
        for foreign_key in dynamics.foreign_keys
    }
    assert foreign_keys == {
        "country_id": ("countries", "RESTRICT"),
        "tax_benefit_model_id": ("tax_benefit_models", "RESTRICT"),
        "tax_benefit_model_version_id": ("tax_benefit_model_versions", "RESTRICT"),
    }
    unique_column_sets = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in dynamics.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    }
    assert unique_column_sets == {
        "uq_dynamics_id_country": ("id", "country_id"),
        "uq_dynamics_canonicalization_content_hash": (
            "canonicalization_version",
            "content_hash",
        ),
    }
    check_names = {
        constraint.name
        for constraint in dynamics.constraints
        if isinstance(constraint, sa.CheckConstraint)
    }
    assert check_names == {
        "ck_dynamics_canonicalization_version",
        "ck_dynamics_content_hash_length",
    }


def test_a_dynamic_s_values_are_unique_per_parameter_and_start_date() -> None:
    parameter_values = V2_METADATA.tables["parameter_values"]
    index = next(
        index
        for index in parameter_values.indexes
        if index.name == "uq_parameter_values_dynamic_parameter_start_date"
    )

    assert index.unique
    assert tuple(column.name for column in index.columns) == (
        "dynamic_id",
        "parameter_id",
        "start_date",
    )
    assert str(index.dialect_options["postgresql"]["where"]) == (
        "dynamic_id IS NOT NULL"
    )
    assert str(index.dialect_options["sqlite"]["where"]) == "dynamic_id IS NOT NULL"


def test_legacy_policy_mappings_name_an_optional_dynamic_of_their_country() -> None:
    mappings = V2_METADATA.tables["legacy_policy_mappings"]

    assert mappings.c.dynamic_id.nullable
    (dynamic_key,) = (
        constraint
        for constraint in mappings.constraints
        if isinstance(constraint, sa.ForeignKeyConstraint)
        and constraint.referred_table.name == "dynamics"
    )
    assert dynamic_key.name == "fk_legacy_policy_mappings_dynamic_country"
    assert [column.name for column in dynamic_key.columns] == [
        "dynamic_id",
        "country_id",
    ]
    assert [element.target_fullname for element in dynamic_key.elements] == [
        "dynamics.id",
        "dynamics.country_id",
    ]
    assert dynamic_key.ondelete == "RESTRICT"
    assert any(
        index.name == "ix_legacy_policy_mappings_dynamic"
        and [column.name for column in index.columns] == ["dynamic_id"]
        for index in mappings.indexes
    )


def test_identical_dynamic_content_is_stored_once() -> None:
    engine = _sqlite_engine_with_foreign_keys()
    model, version, parameter = _catalog()

    with Session(engine) as session:
        session.add_all([model, version, parameter])
        session.commit()
        session.add(_dynamic(model, version))
        session.commit()
        session.add(_dynamic(model, version))
        with pytest.raises(IntegrityError, match="UNIQUE constraint failed"):
            session.commit()
        session.rollback()
        session.add(_dynamic(model, version, content_hash="e" * 64))
        session.commit()

    engine.dispose()


def test_a_dynamic_sets_one_value_per_parameter_and_start_date() -> None:
    engine = _sqlite_engine_with_foreign_keys()
    model, version, parameter = _catalog()

    with Session(engine) as session:
        session.add_all([model, version, parameter])
        session.commit()
        dynamic = _dynamic(model, version)
        session.add(dynamic)
        session.commit()
        for value in (0.1, 0.2):
            session.add(
                ParameterValue(
                    parameter_id=parameter.id,
                    dynamic_id=dynamic.id,
                    value_json=value,
                    start_date=START_DATE,
                )
            )
        with pytest.raises(IntegrityError, match="UNIQUE constraint failed"):
            session.commit()

    engine.dispose()


def test_a_mapping_cannot_name_another_country_s_dynamic() -> None:
    engine = _sqlite_engine_with_foreign_keys()
    model, version, _parameter = _catalog()

    with Session(engine) as session:
        policy = Policy(
            country_id="uk",
            tax_benefit_model_id=model.id,
            tax_benefit_model_version_id=version.id,
            canonicalization_version=1,
            content_hash="a" * 64,
        )
        session.add_all([model, version, policy])
        session.commit()
        us_dynamic = _dynamic(model, version)
        session.add(us_dynamic)
        session.commit()
        session.add(
            LegacyPolicyMapping(
                country_id="uk",
                legacy_policy_id=7,
                policy_id=policy.id,
                dynamic_id=us_dynamic.id,
                source_policy_hash="v1-hash",
            )
        )
        with pytest.raises(IntegrityError, match="FOREIGN KEY constraint failed"):
            session.commit()

    engine.dispose()


def test_the_v2_mappers_configure_without_relationship_warnings() -> None:
    # A fresh interpreter, since a process configures its mappers only once
    # and an error there would break every later mapper in this one.
    configuration = subprocess.run(
        [
            sys.executable,
            "-c",
            "import warnings\n"
            "from sqlalchemy.exc import SAWarning\n"
            "warnings.simplefilter('error', SAWarning)\n"
            "import policyengine_api.data.v2.models\n"
            "from sqlalchemy.orm import configure_mappers\n"
            "configure_mappers()",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert configuration.returncode == 0, configuration.stderr


def test_a_dynamic_is_stored_in_one_flush_with_its_new_catalog_version() -> None:
    engine = _sqlite_engine_with_foreign_keys()
    model, version, parameter = _catalog()

    with Session(engine) as session:
        dynamic = Dynamic(
            country_id="us",
            tax_benefit_model=model,
            tax_benefit_model_version=version,
            canonicalization_version=1,
            content_hash="d" * 64,
        )
        session.add_all([parameter, dynamic])
        session.commit()
        stored = session.get(Dynamic, dynamic.id)

        assert stored is not None
        assert stored.tax_benefit_model_version_id == version.id
        assert stored in version.dynamics

    engine.dispose()
