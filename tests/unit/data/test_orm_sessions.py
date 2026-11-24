import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

import policyengine_api.data.orm as orm_module
from policyengine_api.data.orm import get_v1_session_factory
from policyengine_api.data.v1_models import Household
from tests.fixtures.database_sessions import serve_v1_sessions, sqlite_v1_sessions


def _household(household_hash: str) -> Household:
    return Household(
        country_id="us",
        api_version="1.0.0",
        household_json={},
        household_hash=household_hash,
    )


def _stored_household_hashes(session: Session) -> list[str]:
    return list(
        session.scalars(select(Household.household_hash).order_by(Household.id))
    )


def test_session_factory_creates_distinct_sessions_bound_to_one_engine():
    with sqlite_v1_sessions() as factory:
        first = factory()
        second = factory()
        try:
            assert isinstance(first, Session)
            assert isinstance(second, Session)
            assert first is not second
            assert first.expire_on_commit is False
            # A row one session commits is the other's: both reach one database.
            first.add(_household("shared"))
            first.commit()
            assert _stored_household_hashes(second) == ["shared"]
        finally:
            first.close()
            second.close()


def test_session_factory_begin_commits_and_rolls_back():
    with sqlite_v1_sessions() as factory:
        with factory.begin() as session:
            session.add(_household("committed"))

        def insert_then_fail() -> None:
            with factory.begin() as session:
                session.add(_household("rolled back"))
                session.flush()
                msg = "stop"
                raise RuntimeError(msg)

        with pytest.raises(RuntimeError, match="stop"):
            insert_then_fail()

        with factory() as session:
            assert _stored_household_hashes(session) == ["committed"]


def test_runtime_factory_is_cached_and_has_no_local_selector(monkeypatch):
    with sqlite_v1_sessions() as remote_sessions:
        serve_v1_sessions(monkeypatch, remote_sessions)
        try:
            remote = get_v1_session_factory()

            assert remote is get_v1_session_factory()
            # The factory opens the served engine's database, not one of its own.
            with remote_sessions.begin() as session:
                session.add(_household("served"))
            with remote() as session:
                assert _stored_household_hashes(session) == ["served"]
        finally:
            orm_module.clear_v1_session_factories()
