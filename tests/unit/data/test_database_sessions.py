"""Tests of the tests' SQLite Session factories in tests/fixtures/database_sessions.py.

tests/integration/test_database_sessions.py tests the PostgreSQL and MySQL
ones, and the role, grant and cleanup statements.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlmodel import col

from policyengine_api.data import orm
from policyengine_api.data.v1_models import Policy, UserProfile, V1Base
from policyengine_api.data.v2.models import TaxBenefitModel, TaxBenefitModelVersion
from tests.fixtures.database_sessions import (
    act_as,
    delete_all_rows,
    recorded_statements,
    schema_inspector,
    sqlite_v1_sessions,
    sqlite_v2_sessions,
    v2_role_sessions,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


def _version_of_a_missing_model() -> TaxBenefitModelVersion:
    return TaxBenefitModelVersion(
        model_id=TaxBenefitModel().id,
        version="1.0.0",
        current_law_id=1,
        metadata_time_periods=[2026],
    )


def _policy(policy_hash: str) -> Policy:
    return Policy(
        country_id="us",
        label="A reform",
        api_version="1.0.0",
        policy_json={},
        policy_hash=policy_hash,
    )


def test_sqlite_v2_sessions_enforce_foreign_keys_when_asked() -> None:
    with sqlite_v2_sessions(foreign_keys=True) as sessions, sessions() as session:
        session.add(_version_of_a_missing_model())
        with pytest.raises(IntegrityError, match="FOREIGN KEY"):
            session.flush()


def test_sqlite_v2_sessions_ignore_foreign_keys_by_default() -> None:
    with sqlite_v2_sessions() as sessions:
        with sessions.begin() as session:
            session.add(_version_of_a_missing_model())
        with sessions() as session:
            stored = session.scalar(
                select(func.count()).select_from(TaxBenefitModelVersion)
            )

    assert stored == 1


def _add_a_model_then_fail(session: Session, name: str) -> None:
    with session.begin_nested():
        session.add(TaxBenefitModel(name=name))
        session.flush()
        raise RuntimeError(name)


def test_sqlite_v2_savepoints_roll_back_only_their_own_rows() -> None:
    with sqlite_v2_sessions() as sessions, sessions() as session:
        session.add(TaxBenefitModel(name="policyengine-us"))
        session.flush()
        with pytest.raises(RuntimeError):
            _add_a_model_then_fail(session, "policyengine-uk")
        names = session.scalars(select(col(TaxBenefitModel.name))).all()

    assert names == ["policyengine-us"]


def test_sqlite_v1_sessions_number_policies_as_api_v1_does() -> None:
    with sqlite_v1_sessions() as sessions:
        with sessions.begin() as session:
            session.add_all([_policy("first"), _policy("second")])
        with sessions() as session:
            numbered = session.execute(
                select(Policy.policy_hash, Policy.id).order_by(Policy.id)
            ).all()

    assert [tuple(row) for row in numbered] == [("first", 1), ("second", 2)]


def test_sqlite_v1_sessions_store_json_with_the_given_serializer() -> None:
    serialized: list[object] = []

    def serialize(value: object) -> str:
        serialized.append(value)
        return json.dumps(value)

    with (
        sqlite_v1_sessions(json_serializer=serialize) as sessions,
        sessions.begin() as session,
    ):
        session.add(_policy("hash"))

    assert serialized == [{}]


def test_serving_v1_sessions_points_api_v1s_factory_at_them(
    v1_test_sessions: sessionmaker[Session],
) -> None:
    with v1_test_sessions.begin() as session:
        session.add(_policy("served"))

    with orm.get_v1_session_factory()() as session:
        hashes = session.scalars(select(Policy.policy_hash)).all()

    assert hashes == ["served"]


def test_delete_all_rows_empties_every_table_of_the_registry() -> None:
    with sqlite_v1_sessions() as sessions:
        with sessions.begin() as session:
            session.add(_policy("hash"))
            session.add(
                UserProfile(
                    auth0_id="auth0|someone", primary_country="us", user_since=1
                )
            )
        with sessions.begin() as session:
            delete_all_rows(session, V1Base.registry)
        with sessions() as session:
            remaining = [
                session.scalar(select(func.count()).select_from(model))
                for model in (Policy, UserProfile)
            ]

    assert remaining == [0, 0]


def test_the_schema_inspector_reads_a_session_or_its_factory() -> None:
    with sqlite_v2_sessions() as sessions, sessions() as session:
        from_factory = schema_inspector(sessions).get_table_names()
        from_session = schema_inspector(session).get_table_names()

    assert "reports" in from_factory
    assert from_session == from_factory


def test_recorded_statements_are_the_sql_sent_inside() -> None:
    with sqlite_v2_sessions() as sessions, sessions() as session:
        session.scalars(select(col(TaxBenefitModel.name))).all()
        with recorded_statements(session) as statements:
            session.scalars(select(col(TaxBenefitModelVersion.version))).all()

    assert len(statements) == 1
    assert "FROM tax_benefit_model_versions" in statements[0]


@pytest.mark.parametrize("role", ["Runtime", "runtime; DROP TABLE users", "", "1st"])
def test_a_role_is_named_in_lowercase_letters_digits_and_underscores(
    role: str,
) -> None:
    with sqlite_v2_sessions() as sessions, sessions() as session:
        with pytest.raises(ValueError, match="role names"):
            act_as(session, role)
        with (
            pytest.raises(ValueError, match="role names"),
            v2_role_sessions("postgresql+psycopg://localhost/unused", role),
        ):
            pass
