"""Tests of API v1's Session factories for commands that run once."""

from unittest.mock import Mock

import pytest
from sqlalchemy.pool import NullPool

from policyengine_api.data import v1_sessions
from policyengine_api.data.v1_models import Policy
from tests.fixtures.database_sessions import sqlite_v1_sessions


def test_unpooled_sessions_keep_no_pool_and_dispose_of_their_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = Mock()
    engine_factory = Mock(return_value=engine)
    monkeypatch.setattr(v1_sessions, "create_engine", engine_factory)
    url = "mysql+pymysql://migrator:password@127.0.0.1:3307/policyengine"

    with v1_sessions.unpooled_v1_sessions(url) as sessions:
        assert sessions.kw["expire_on_commit"] is False
        engine.dispose.assert_not_called()

    engine_factory.assert_called_once_with(url, poolclass=NullPool)
    engine.dispose.assert_called_once_with()


def test_schema_inspector_reads_a_factory_and_a_session_in_its_transaction() -> None:
    with sqlite_v1_sessions() as sessions:
        factory_tables = v1_sessions.v1_schema_inspector(sessions).get_table_names()
        with sessions() as session:
            session_tables = v1_sessions.v1_schema_inspector(session).get_table_names()
            assert session.in_transaction()

    assert Policy.__tablename__ in factory_tables
    assert session_tables == factory_tables
