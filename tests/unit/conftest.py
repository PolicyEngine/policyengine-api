import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool


os.environ.setdefault("FLASK_DEBUG", "1")

from policyengine_api.data import orm
from policyengine_api.data.local_database import create_local_v1_schema
from policyengine_api.data.local_models import LocalV1Base
from policyengine_api.data.v1_models import V1Base


@pytest.fixture(scope="session")
def test_engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    create_local_v1_schema(engine)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def isolated_orm_database(test_engine, monkeypatch):
    """Bind runtime factories to a clean in-memory ORM database per test."""

    monkeypatch.setattr(orm, "get_v1_engine", lambda *, local=False: test_engine)
    orm.clear_v1_session_factories()
    factory = orm.get_v1_session_factory()
    with factory.begin() as session:
        local_tables = LocalV1Base.metadata.sorted_tables
        production_tables = V1Base.metadata.sorted_tables
        for table in reversed([*production_tables, *local_tables]):
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
