"""Canonical SQLModel persistence and bounded SQLAlchemy escape-hatch tests."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from policyengine_api.data.v2.models import (
    Country,
    Dynamic,
    Household,
    LegacyPolicyMapping,
    LegacyUserMapping,
    LegacyUserPolicyMapping,
    Parameter,
    ParameterValue,
    Policy,
    TaxBenefitModel,
    TaxBenefitModelVersion,
    User,
    UserHouseholdAssociation,
    UserPolicy,
)
from policyengine_api.data.v2.models.base import DIRECT_SQLALCHEMY_EXCEPTIONS
from tests.fixtures.database_sessions import sqlite_v2_sessions
from tests.fixtures.v2_countries import add_listed_countries
from tests.integration.parameter_values_with_dynamics import (
    ParameterValueWithDynamic,
)


@contextmanager
def _relational_sqlite_session() -> Iterator[Session]:
    """Yield a Session of a SQLite v2 schema that enforces foreign keys."""
    with sqlite_v2_sessions(foreign_keys=True) as sessions:
        with sessions(expire_on_commit=True) as session:
            add_listed_countries(session)
        with sessions(expire_on_commit=True) as session:
            yield session


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
    model = TaxBenefitModel(name="test-country", description="Test model")
    version = TaxBenefitModelVersion(
        model=model,
        version="1.2.3",
        current_law_id=1,
        metadata_time_periods=[2026],
    )

    with sqlite_v2_sessions() as sessions, sessions(expire_on_commit=True) as session:
        session.add(version)
        session.commit()
        statement = select(TaxBenefitModelVersion).where(
            TaxBenefitModelVersion.version == "1.2.3"
        )
        stored = session.exec(statement).one()

        assert stored.model.name == "test-country"
        assert stored.id == version.id


def test_direct_sqlalchemy_categories_are_complete_and_documented() -> None:
    assert set(DIRECT_SQLALCHEMY_EXCEPTIONS) == {
        "timezone_aware_timestamps",
        "named_enums",
        "typed_json_and_text",
        "named_constraints_and_indexes",
        "ambiguous_foreign_key_relationships",
        "transaction_conflict_recovery",
        "columns_left_out_of_the_mapper",
    }
    assert all(DIRECT_SQLALCHEMY_EXCEPTIONS.values())


def test_user_primary_country_must_be_a_listed_country() -> None:

    with _relational_sqlite_session() as session:
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


def test_a_country_row_lets_records_use_a_household_only_country() -> None:
    household_only_country = Country(
        id="be",
        household_enabled=True,
        society_wide_enabled=False,
    )

    with _relational_sqlite_session() as session:
        session.add(User(primary_country="be"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.add(household_only_country)
        session.commit()
        user = User(primary_country="be")
        household = Household(
            country_id="be",
            household_data={"people": {}},
            canonicalization_version=1,
            content_hash="b" * 64,
        )
        session.add_all([user, household])
        session.flush()
        session.add(
            UserHouseholdAssociation(
                user_id=user.id,
                household_id=household.id,
                country_id="be",
            )
        )
        session.commit()

        stored_country = session.exec(select(UserHouseholdAssociation.country_id)).one()
        assert stored_country == "be"


def test_a_listed_country_cannot_be_deleted_while_records_use_it() -> None:

    with _relational_sqlite_session() as session:
        session.add(User(primary_country="uk"))
        session.commit()

        session.delete(session.get(Country, "uk"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_a_society_wide_country_must_also_be_household_capable() -> None:

    with _relational_sqlite_session() as session:
        session.add(
            Country(id="be", household_enabled=False, society_wide_enabled=True)
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_only_unauthenticated_users_may_omit_a_primary_country() -> None:
    with sqlite_v2_sessions() as sessions:
        with sessions(expire_on_commit=True) as session:
            session.add(User(user_type="unauthenticated"))
            session.commit()
        for invalid in (
            User(),
            User(user_type="standard"),
            User(user_type="guest", primary_country="us"),
        ):
            with sessions(expire_on_commit=True) as session:
                session.add(invalid)
                with pytest.raises(IntegrityError):
                    session.commit()
        with sessions.begin() as session:
            # Writers that predate user_type rely on its server default: the
            # INSERT names only these columns, leaving out every default.
            session.execute(
                sa.insert(User).from_select(
                    ["id", "created_at", "primary_country"],
                    sa.select(
                        sa.literal(UUID(int=1), sa.Uuid),
                        sa.func.current_timestamp(),
                        sa.literal("us"),
                    ),
                    include_defaults=False,
                )
            )
            stored_types = session.exec(select(User.user_type).order_by(User.user_type))
            assert list(stored_types) == ["standard", "unauthenticated"]


def test_canonical_parameter_values_are_unique_by_parameter_and_start_date() -> None:
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
    start_date = datetime(2026, 1, 1, tzinfo=UTC)

    with sqlite_v2_sessions() as sessions, sessions(expire_on_commit=True) as session:
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


def test_policy_content_hash_is_unique_per_canonicalization_version() -> None:
    model, version, _parameter, policy = _policy_graph()
    duplicate = Policy(
        country_id="us",
        tax_benefit_model=model,
        tax_benefit_model_version=version,
        canonicalization_version=policy.canonicalization_version,
        content_hash=policy.content_hash,
    )

    with _relational_sqlite_session() as session:
        session.add_all([policy, duplicate])
        with pytest.raises(IntegrityError):
            session.commit()


def test_policy_parameter_value_owner_period_and_identity_constraints() -> None:
    model, version, parameter, policy = _policy_graph(content_hash="b" * 64)
    dynamic = Dynamic(
        country_id="us",
        tax_benefit_model_id=model.id,
        tax_benefit_model_version_id=version.id,
        canonicalization_version=1,
        content_hash="d" * 64,
    )
    start = datetime(2026, 1, 1, tzinfo=UTC)

    with _relational_sqlite_session() as session:
        session.add_all([parameter, policy])
        session.commit()
        session.add(dynamic)
        session.commit()

        # ParameterValue no longer maps dynamic_id, which the table keeps
        # until C1 · 53 drops it with the check.
        with pytest.raises(IntegrityError, match="ck_parameter_values_single_owner"):
            session.execute(
                sa.insert(ParameterValueWithDynamic).values(
                    id=uuid4(),
                    parameter_id=parameter.id,
                    policy_id=policy.id,
                    dynamic_id=dynamic.id,
                    value_json={"rate": 0.1},
                    start_date=start,
                )
            )
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


def test_user_policy_allows_duplicates_but_requires_policy_country() -> None:
    _model, _version, _parameter, policy = _policy_graph(content_hash="c" * 64)
    user = User(primary_country="us")

    with _relational_sqlite_session() as session:
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


def test_legacy_policy_mapping_allows_many_sources_for_one_policy() -> None:
    _model, _version, _parameter, policy = _policy_graph(content_hash="d" * 64)

    with _relational_sqlite_session() as session:
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


def test_legacy_user_policy_mapping_destination_is_unique_and_cascades() -> None:
    _model, _version, _parameter, policy = _policy_graph(content_hash="e" * 64)
    user = User(primary_country="us")

    with _relational_sqlite_session() as session:
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


def test_legacy_user_mapping_is_one_to_one_and_profile_fields_are_optional() -> None:

    with _relational_sqlite_session() as session:
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
