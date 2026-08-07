import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

import policyengine_api.data.orm as orm_module
from policyengine_api.data.orm import (
    SessionManager,
    build_session_factory,
    build_sqlite_session_manager,
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


def test_runtime_factories_are_cached_and_separate(monkeypatch):
    remote_engine = create_engine("sqlite+pysqlite:///:memory:")
    local_engine = create_engine("sqlite+pysqlite:///:memory:")

    monkeypatch.setattr(
        orm_module,
        "get_v1_engine",
        lambda *, local=False: local_engine if local else remote_engine,
    )
    orm_module.clear_v1_session_factories()

    try:
        remote = get_v1_session_factory()
        local = get_v1_session_factory(local=True)

        assert remote is get_v1_session_factory()
        assert local is get_v1_session_factory(local=True)
        assert remote is not local
        assert remote.kw["bind"] is remote_engine
        assert local.kw["bind"] is local_engine
    finally:
        orm_module.clear_v1_session_factories()


def test_session_manager_commits_successful_transaction():
    manager = build_sqlite_session_manager()
    with manager.engine.begin() as connection:
        connection.execute(text("CREATE TABLE item (id INTEGER PRIMARY KEY)"))

    manager.run_in_transaction(
        lambda session: session.execute(text("INSERT INTO item (id) VALUES (1)"))
    )

    with manager.session() as session:
        assert session.execute(text("SELECT id FROM item")).scalar_one() == 1


def test_session_manager_rolls_back_failed_transaction():
    manager = build_sqlite_session_manager()
    with manager.engine.begin() as connection:
        connection.execute(text("CREATE TABLE item (id INTEGER PRIMARY KEY)"))

    def fail(session):
        session.execute(text("INSERT INTO item (id) VALUES (1)"))
        raise RuntimeError("stop")

    with pytest.raises(RuntimeError, match="stop"):
        manager.run_in_transaction(fail)

    with manager.session() as session:
        assert session.execute(text("SELECT COUNT(*) FROM item")).scalar_one() == 0


def test_session_manager_closes_sessions_after_callback(monkeypatch):
    manager = build_sqlite_session_manager()
    closed = []
    original_close = manager.session_factory.class_.close

    def recording_close(session):
        closed.append(session)
        return original_close(session)

    monkeypatch.setattr(manager.session_factory.class_, "close", recording_close)
    manager.run_in_transaction(lambda session: None)

    assert len(closed) == 1


def test_session_manager_requires_an_engine():
    with pytest.raises(TypeError):
        SessionManager()  # type: ignore[call-arg]
