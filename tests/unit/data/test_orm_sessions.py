import pytest
from sqlalchemy import text

from policyengine_api.data.orm import SessionManager, build_sqlite_session_manager


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
