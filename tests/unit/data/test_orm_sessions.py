import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

import policyengine_api.data.orm as orm_module
from policyengine_api.data.orm import (
    build_session_factory,
    get_v1_session_factory,
)


def test_session_factory_creates_distinct_sessions_bound_to_one_engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    factory = build_session_factory(engine)

    first = factory()
    second = factory()
    try:
        assert isinstance(first, Session)
        assert isinstance(second, Session)
        assert first is not second
        assert first.get_bind() is engine
        assert second.get_bind() is engine
        assert first.expire_on_commit is False
    finally:
        first.close()
        second.close()


def test_session_factory_begin_commits_and_rolls_back():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    factory = build_session_factory(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE item (id INTEGER PRIMARY KEY)"))

    with factory.begin() as session:
        session.execute(text("INSERT INTO item (id) VALUES (1)"))

    with pytest.raises(RuntimeError, match="stop"):
        with factory.begin() as session:
            session.execute(text("INSERT INTO item (id) VALUES (2)"))
            raise RuntimeError("stop")

    with factory() as session:
        assert session.scalars(text("SELECT id FROM item ORDER BY id")).all() == [1]


def test_runtime_factory_is_cached_and_has_no_local_selector(monkeypatch):
    remote_engine = create_engine("sqlite+pysqlite:///:memory:")

    monkeypatch.setattr(
        orm_module,
        "get_v1_engine",
        lambda: remote_engine,
    )
    orm_module.clear_v1_session_factories()

    try:
        remote = get_v1_session_factory()

        assert remote is get_v1_session_factory()
        assert remote.kw["bind"] is remote_engine
    finally:
        orm_module.clear_v1_session_factories()
