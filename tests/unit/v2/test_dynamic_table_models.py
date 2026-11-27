"""Dynamics are stored as policies are: once per canonical content hash."""

import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session

from policyengine_api.data.v2.models import (
    Dynamic,
    LegacyPolicyMapping,
    Parameter,
    ParameterValue,
    Policy,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)
from tests.fixtures.database_sessions import sqlite_v2_sessions
from tests.fixtures.v2_countries import add_listed_countries
from tests.integration.parameter_values_with_dynamics import (
    ParameterValueWithDynamic,
)
from tests.unit.v2.v2_schema_reading import (
    declared_index,
    model_columns,
    stored_v2_table,
)

START_DATE = datetime(2026, 1, 1, tzinfo=UTC)


@contextmanager
def _sqlite_sessions_with_foreign_keys() -> Iterator[sessionmaker[Session]]:
    with sqlite_v2_sessions(foreign_keys=True) as sessions:
        with sessions(expire_on_commit=True) as session:
            add_listed_countries(session)
        yield sessions


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
    dynamics = model_columns("dynamics")
    policies = model_columns("policies")
    stored_dynamics = stored_v2_table("dynamics")

    assert set(dynamics.keys()) == set(policies.keys())
    assert "name" not in dynamics
    assert "description" not in dynamics
    for column_name in (
        "country_id",
        "tax_benefit_model_id",
        "tax_benefit_model_version_id",
        "canonicalization_version",
        "content_hash",
    ):
        assert not dynamics[column_name].nullable
    assert stored_dynamics.references_by_column == {
        "country_id": ("countries", "RESTRICT"),
        "tax_benefit_model_id": ("tax_benefit_models", "RESTRICT"),
        "tax_benefit_model_version_id": ("tax_benefit_model_versions", "RESTRICT"),
    }
    assert stored_dynamics.unique_constraints == {
        "uq_dynamics_id_country": ("id", "country_id"),
        "uq_dynamics_canonicalization_content_hash": (
            "canonicalization_version",
            "content_hash",
        ),
    }
    assert set(stored_dynamics.checks) == {
        "ck_dynamics_canonicalization_version",
        "ck_dynamics_content_hash_length",
    }


def test_a_dynamic_s_values_are_unique_per_parameter_and_start_date() -> None:
    index = declared_index(
        ParameterValue, "uq_parameter_values_dynamic_parameter_start_date"
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
    mappings = stored_v2_table("legacy_policy_mappings")

    assert model_columns("legacy_policy_mappings").dynamic_id.nullable
    (dynamic_key,) = mappings.foreign_keys_to("dynamics")
    assert dynamic_key.name == "fk_legacy_policy_mappings_dynamic_country"
    assert dynamic_key.columns == ("dynamic_id", "country_id")
    assert dynamic_key.targets == ("dynamics.id", "dynamics.country_id")
    assert dynamic_key.ondelete == "RESTRICT"
    assert mappings.index_columns.get("ix_legacy_policy_mappings_dynamic") == (
        "dynamic_id",
    )


def test_identical_dynamic_content_is_stored_once() -> None:
    model, version, parameter = _catalog()

    with (
        _sqlite_sessions_with_foreign_keys() as sessions,
        sessions(expire_on_commit=True) as session,
    ):
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


def test_a_dynamic_sets_one_value_per_parameter_and_start_date() -> None:
    """The table keeps the rule while it keeps ``dynamic_id``.

    ``ParameterValue`` no longer maps the column, so the values are written
    through the column-only ``ParameterValueWithDynamic``.
    """
    model, version, parameter = _catalog()

    with (
        _sqlite_sessions_with_foreign_keys() as sessions,
        sessions(expire_on_commit=True) as session,
    ):
        session.add_all([model, version, parameter])
        session.commit()
        dynamic = _dynamic(model, version)
        session.add(dynamic)
        session.commit()
        dynamic_value = {
            "parameter_id": parameter.id,
            "dynamic_id": dynamic.id,
            "start_date": START_DATE,
        }
        session.execute(
            insert(ParameterValueWithDynamic).values(
                id=uuid4(), value_json=0.1, **dynamic_value
            )
        )
        with pytest.raises(IntegrityError, match="UNIQUE constraint failed"):
            session.execute(
                insert(ParameterValueWithDynamic).values(
                    id=uuid4(), value_json=0.2, **dynamic_value
                )
            )


def test_a_mapping_cannot_name_another_country_s_dynamic() -> None:
    model, version, _parameter = _catalog()

    with (
        _sqlite_sessions_with_foreign_keys() as sessions,
        sessions(expire_on_commit=True) as session,
    ):
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
    model, version, parameter = _catalog()

    with (
        _sqlite_sessions_with_foreign_keys() as sessions,
        sessions(expire_on_commit=True) as session,
    ):
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
