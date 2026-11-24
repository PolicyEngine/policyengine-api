from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

os.environ.setdefault("FLASK_DEBUG", "1")

from policyengine_api.data import orm
from policyengine_api.data.v1_models import V1Base
from tests.fixtures.database_sessions import (
    delete_all_rows,
    serve_v1_sessions,
    sqlite_v1_sessions,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="session")
def v1_test_sessions() -> Iterator[sessionmaker[Session]]:
    """Return Session factories of an in-memory SQLite copy of API v1's schema."""
    with sqlite_v1_sessions() as sessions:
        yield sessions


@pytest.fixture(autouse=True)
def isolated_orm_database(
    v1_test_sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Bind runtime factories to a clean in-memory ORM database per test."""
    serve_v1_sessions(monkeypatch, v1_test_sessions)
    with orm.get_v1_session_factory().begin() as session:
        delete_all_rows(session, V1Base.registry)
    try:
        yield
    finally:
        orm.clear_v1_session_factories()


@pytest.fixture
def orm_session_factory(isolated_orm_database: None) -> sessionmaker[Session]:
    return orm.get_v1_session_factory()


@pytest.fixture
def orm_session(orm_session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with orm_session_factory() as session:
        yield session
