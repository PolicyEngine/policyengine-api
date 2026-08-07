import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool


os.environ.setdefault("FLASK_DEBUG", "1")

from policyengine_api.constants import REPO
from policyengine_api.data import orm
from policyengine_api.data.v1_models import V1Base


@pytest.fixture(scope="session")
def test_engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    initialization_sql = (
        REPO / "policyengine_api" / "data" / "initialise_local.sql"
    ).read_text(encoding="utf-8")
    raw_connection = engine.raw_connection()
    try:
        raw_connection.executescript(initialization_sql)
    finally:
        raw_connection.close()
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def isolated_orm_database(test_engine, monkeypatch):
    """Bind runtime factories to a clean in-memory ORM database per test."""

    monkeypatch.setattr(orm, "get_v1_engine", lambda *, local=False: test_engine)
    orm.clear_v1_session_factories()
    factory = orm.get_v1_session_factory()
    with factory.begin() as session:
        for table in reversed(V1Base.metadata.sorted_tables):
            session.execute(table.delete())
    try:
        yield
    finally:
        orm.clear_v1_session_factories()


@pytest.fixture
def orm_session_factory(isolated_orm_database):
    return orm.get_v1_session_factory()


@pytest.fixture
def orm_session(orm_session_factory):
    with orm_session_factory() as session:
        yield session
