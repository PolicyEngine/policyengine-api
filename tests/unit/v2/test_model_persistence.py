"""Canonical SQLModel persistence and bounded SQLAlchemy escape-hatch tests."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, create_engine, select

from policyengine_api.data.v2.models import (
    Dynamic,
    LegacyPolicyMapping,
    LegacyUserMapping,
    LegacyUserPolicyMapping,
    Parameter,
    ParameterValue,
    Policy,
    TaxBenefitModel,
    TaxBenefitModelVersion,
    User,
    UserPolicy,
    V2_METADATA,
)
from policyengine_api.data.v2.models.base import DIRECT_SQLALCHEMY_EXCEPTIONS


def _relational_sqlite_engine():
    engine = create_engine("sqlite://")

    @sa.event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    V2_METADATA.create_all(engine)
    return engine


def _policy_graph(*, content_hash: str = "a" * 64):
    model = TaxBenefitModel(name=f"policy-model-{content_hash[:8]}")
    version = TaxBenefitModelVersion(
        model=model,
        version="5.2.0",
        current_law_id=1,
        metadata_time_periods=[2026],
    )
    parameter = Parameter(
        name="gov.example.rate",
        tax_benefit_model_version=version,
    )
    policy = Policy(
        country_id="us",
        tax_benefit_model=model,
        tax_benefit_model_version=version,
        canonicalization_version=1,
        content_hash=content_hash,
    )
    return model, version, parameter, policy


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


def test_policy_content_hash_is_unique_per_canonicalization_version() -> None:
    engine = _relational_sqlite_engine()
    model, version, _parameter, policy = _policy_graph()
    duplicate = Policy(
        country_id="us",
        tax_benefit_model=model,
        tax_benefit_model_version=version,
        canonicalization_version=policy.canonicalization_version,
        content_hash=policy.content_hash,
    )

    with Session(engine) as session:
        session.add_all([policy, duplicate])
        with pytest.raises(IntegrityError):
            session.commit()

    engine.dispose()


def test_policy_parameter_value_owner_period_and_identity_constraints() -> None:
    engine = _relational_sqlite_engine()
    _model, _version, parameter, policy = _policy_graph(content_hash="b" * 64)
    dynamic = Dynamic(name="dynamic")
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    with Session(engine) as session:
        session.add_all([parameter, policy, dynamic])
        session.commit()

        invalid_owner = ParameterValue(
            parameter_id=parameter.id,
            policy_id=policy.id,
            dynamic_id=dynamic.id,
            value_json={"rate": 0.1},
            start_date=start,
        )
        session.add(invalid_owner)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        invalid_period = ParameterValue(
            parameter_id=parameter.id,
            policy_id=policy.id,
            value_json={"rate": 0.1},
            start_date=start,
            end_date=start - timedelta(seconds=1),
        )
        session.add(invalid_period)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.add_all(
            [
                ParameterValue(
                    parameter_id=parameter.id,
                    policy_id=policy.id,
                    value_json={"rate": 0.1},
                    start_date=start,
                ),
                ParameterValue(
                    parameter_id=parameter.id,
                    policy_id=policy.id,
                    value_json={"rate": 0.2},
                    start_date=start,
                ),
            ]
        )
        with pytest.raises(IntegrityError):
            session.commit()

    engine.dispose()


def test_user_policy_allows_duplicates_but_requires_policy_country() -> None:
    engine = _relational_sqlite_engine()
    _model, _version, _parameter, policy = _policy_graph(content_hash="c" * 64)
    user = User(primary_country="us")

    with Session(engine) as session:
        session.add_all([policy, user])
        session.commit()
        first = UserPolicy(
            country_id="us",
            user_id=user.id,
            policy_id=policy.id,
            name="First",
        )
        second = UserPolicy(
            country_id="us",
            user_id=user.id,
            policy_id=policy.id,
            name="Second",
        )
        session.add_all([first, second])
        session.commit()

        assert first.id != second.id

        session.add(
            UserPolicy(
                country_id="uk",
                user_id=user.id,
                policy_id=policy.id,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()

    engine.dispose()


def test_legacy_policy_mapping_allows_many_sources_for_one_policy() -> None:
    engine = _relational_sqlite_engine()
    _model, _version, _parameter, policy = _policy_graph(content_hash="d" * 64)

    with Session(engine) as session:
        session.add(policy)
        session.commit()
        session.add_all(
            [
                LegacyPolicyMapping(
                    country_id="us",
                    legacy_policy_id=101,
                    policy_id=policy.id,
                    source_policy_hash="1" * 64,
                ),
                LegacyPolicyMapping(
                    country_id="us",
                    legacy_policy_id=102,
                    policy_id=policy.id,
                    source_policy_hash="2" * 64,
                ),
            ]
        )
        session.commit()

        assert len(policy.legacy_mappings) == 2

        session.add(
            LegacyPolicyMapping(
                country_id="us",
                legacy_policy_id=101,
                policy_id=policy.id,
                source_policy_hash="3" * 64,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()

    engine.dispose()


def test_legacy_user_policy_mapping_destination_is_unique_and_cascades() -> None:
    engine = _relational_sqlite_engine()
    _model, _version, _parameter, policy = _policy_graph(content_hash="e" * 64)
    user = User(primary_country="us")

    with Session(engine) as session:
        association = UserPolicy(
            country_id="us",
            user=user,
            policy=policy,
        )
        mapping = LegacyUserPolicyMapping(
            country_id="us",
            legacy_user_policy_id=201,
            association=association,
            fingerprint_version=1,
            fingerprint_sha256="4" * 64,
        )
        session.add(mapping)
        session.commit()
        assert mapping.created_at is not None
        assert mapping.updated_at is not None

        session.add(
            LegacyUserPolicyMapping(
                country_id="us",
                legacy_user_policy_id=202,
                user_policy_id=association.id,
                fingerprint_version=1,
                fingerprint_sha256="5" * 64,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.delete(association)
        session.commit()
        stored_mapping = session.exec(
            select(LegacyUserPolicyMapping).where(
                LegacyUserPolicyMapping.id == mapping.id
            )
        ).one_or_none()
        assert stored_mapping is None

        stored_policy = session.get(Policy, policy.id)
        assert stored_policy is not None

    engine.dispose()


def test_legacy_user_mapping_is_one_to_one_and_profile_fields_are_optional() -> None:
    engine = _relational_sqlite_engine()

    with Session(engine) as session:
        user = User(primary_country="us")
        session.add(user)
        session.commit()
        mapping = LegacyUserMapping(
            legacy_user_id="legacy-user",
            user_id=user.id,
        )
        session.add(mapping)
        session.commit()

        assert mapping.user_id == user.id
        assert user.first_name is None
        assert user.last_name is None
        assert user.email is None
        assert mapping.created_at is not None

        session.add(
            LegacyUserMapping(
                legacy_user_id="another-legacy-user",
                user_id=user.id,
            )
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
