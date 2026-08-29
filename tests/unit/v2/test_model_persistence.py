"""Canonical SQLModel persistence and bounded SQLAlchemy escape-hatch tests."""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, create_engine, select

from policyengine_api.data.v2.models import (
    Parameter,
    ParameterValue,
    TaxBenefitModel,
    TaxBenefitModelVersion,
    User,
    V2_METADATA,
)
from policyengine_api.data.v2.models.base import DIRECT_SQLALCHEMY_EXCEPTIONS


def test_ordinary_persistence_uses_sqlmodel_session_select_and_exec() -> None:
    # SQLite exists only as an injected, in-memory unit-test fixture. Runtime
    # v2 settings reject it and application code never selects it.
    engine = create_engine("sqlite://")
    V2_METADATA.create_all(engine)
    model = TaxBenefitModel(name="test-country", description="Test model")
    version = TaxBenefitModelVersion(
        model=model,
        version="1.2.3",
        current_law_id=1,
        metadata_time_periods=[2026],
    )

    with Session(engine) as session:
        session.add(version)
        session.commit()
        statement = select(TaxBenefitModelVersion).where(
            TaxBenefitModelVersion.version == "1.2.3"
        )
        stored = session.exec(statement).one()

        assert stored.model.name == "test-country"
        assert stored.id == version.id

    engine.dispose()


def test_direct_sqlalchemy_categories_are_complete_and_documented() -> None:
    assert set(DIRECT_SQLALCHEMY_EXCEPTIONS) == {
        "timezone_aware_timestamps",
        "named_enums",
        "typed_json_and_text",
        "named_constraints_and_indexes",
        "ambiguous_foreign_key_relationships",
        "transaction_conflict_recovery",
    }
    assert all(DIRECT_SQLALCHEMY_EXCEPTIONS.values())


def test_user_primary_country_can_change_between_us_and_uk_only() -> None:
    engine = create_engine("sqlite://")
    V2_METADATA.create_all(engine)

    with Session(engine) as session:
        user = User(
            first_name="Ada",
            last_name="Lovelace",
            email="ada@example.test",
            primary_country="us",
        )
        session.add(user)
        session.commit()

        user.primary_country = "uk"
        session.add(user)
        session.commit()
        assert user.primary_country == "uk"

        user.primary_country = "ca"
        session.add(user)
        with pytest.raises(IntegrityError):
            session.commit()

    engine.dispose()


def test_canonical_parameter_values_are_unique_by_parameter_and_start_date() -> None:
    engine = create_engine("sqlite://")
    V2_METADATA.create_all(engine)
    model = TaxBenefitModel(name="canonical-values")
    version = TaxBenefitModelVersion(
        model=model,
        version="4.20.3",
        current_law_id=1,
        metadata_time_periods=[2026],
    )
    parameter = Parameter(
        name="gov.example.rate",
        tax_benefit_model_version=version,
    )
    start_date = datetime(2026, 1, 1, tzinfo=timezone.utc)

    with Session(engine) as session:
        session.add_all(
            [
                ParameterValue(
                    parameter=parameter,
                    value_json=0.1,
                    start_date=start_date,
                ),
                ParameterValue(
                    parameter=parameter,
                    value_json=0.2,
                    start_date=start_date,
                ),
            ]
        )
        with pytest.raises(IntegrityError):
            session.commit()

    engine.dispose()


def test_v2_models_do_not_create_a_parallel_sqlalchemy_orm_layer() -> None:
    models_directory = (
        Path(__file__).parents[3] / "policyengine_api" / "data" / "v2" / "models"
    )
    model_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(models_directory.glob("*.py"))
    )

    assert "declarative_base" not in model_sources
    assert "mapped_column" not in model_sources
    assert "sqlalchemy.orm.Session" not in model_sources
    assert "class_=sqlalchemy" not in model_sources
