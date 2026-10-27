from pathlib import Path
from typing import NamedTuple
from unittest.mock import Mock

import pytest
import sqlalchemy
from pymysql.constants import CLIENT

from policyengine_api.data import orm


class FakeCloudSqlConnector:
    """Records the options it is built with and every connect call it receives."""

    def __init__(self, **connector_options):
        self.connector_options = connector_options
        self.connect_calls = []

    def connect(self, **connect_options):
        self.connect_calls.append(connect_options)
        return object()

    def close(self):
        pass


class RemoteEngineBuild(NamedTuple):
    """What _build_remote_engine returned and what it passed to its dependencies."""

    engine: object
    connector: FakeCloudSqlConnector
    create_engine_calls: list


@pytest.fixture
def remote_engine_build(monkeypatch):
    """Build the remote engine with a fake connector and a recording create_engine."""
    connectors = []
    engine_calls = []

    def connector_factory(**connector_options):
        connector = FakeCloudSqlConnector(**connector_options)
        connectors.append(connector)
        return connector

    monkeypatch.setattr(orm, "_cloud_sql_state", orm._CloudSqlState())
    monkeypatch.setattr(orm, "Connector", connector_factory)
    monkeypatch.setattr(
        orm,
        "create_engine",
        lambda url, **options: engine_calls.append((url, options)) or "engine",
    )
    monkeypatch.setenv(
        "POLICYENGINE_DB_INSTANCE_CONNECTION_NAME", "project:region:instance"
    )
    monkeypatch.setenv("POLICYENGINE_DB_USER", "user")
    monkeypatch.setenv("POLICYENGINE_DB_NAME", "database")
    monkeypatch.setenv("POLICYENGINE_DB_PASSWORD", "password")

    engine = orm._build_remote_engine()

    [connector] = connectors
    return RemoteEngineBuild(engine, connector, engine_calls)


def test_sqlalchemy_v2_or_newer_is_installed():
    assert int(sqlalchemy.__version__.split(".")[0]) >= 2


def test_remote_engine_delegates_connections_and_pooling_to_sqlalchemy(
    remote_engine_build,
):
    connector = remote_engine_build.connector

    assert remote_engine_build.engine == "engine"
    assert connector.connector_options == {
        "ip_type": orm.IPTypes.PUBLIC,
        "refresh_strategy": "LAZY",
    }
    url, options = remote_engine_build.create_engine_calls[0]
    assert url == "mysql+pymysql://"
    assert options["pool_pre_ping"] is True
    assert options["pool_recycle"] == 1800
    assert options["pool_size"] == 5
    assert options["max_overflow"] == 2
    assert options["pool_timeout"] == 30
    assert connector.connect_calls == []
    options["creator"]()
    assert connector.connect_calls == [
        {
            "instance_connection_string": "project:region:instance",
            "driver": "pymysql",
            "db": "database",
            "user": "user",
            "password": "password",
            "client_flag": CLIENT.FOUND_ROWS,
        }
    ]


def test_remote_engine_connections_report_rows_matched_by_updates(
    remote_engine_build,
):
    """SQLAlchemy checks UPDATE row counts and needs MySQL to count matched rows.

    SQLAlchemy sets CLIENT.FOUND_ROWS itself only when it opens a connection
    from a URL. Through creator= it does not, so the connector call must.
    """
    _url, options = remote_engine_build.create_engine_calls[0]

    options["creator"]()

    [connect_options] = remote_engine_build.connector.connect_calls
    client_flag = connect_options.get("client_flag", 0)
    assert client_flag & CLIENT.FOUND_ROWS == CLIENT.FOUND_ROWS


def test_production_orm_has_no_sqlite_debug_or_local_schema_path():
    source = Path(orm.__file__).read_text(encoding="utf-8")
    for prohibited in (
        "sqlite",
        "FLASK_DEBUG",
        "local=True",
        "local_database",
        "create_all",
        "policyengine.db",
        ".init.lock",
        ".dbpw",
    ):
        assert prohibited not in source


def test_close_v1_engines_disposes_pools_and_connectors(monkeypatch):
    engine = Mock()
    connector = Mock()
    monkeypatch.setattr(orm._cloud_sql_state, "engine", engine)
    monkeypatch.setattr(orm._cloud_sql_state, "connector", connector)
    monkeypatch.setattr(orm._cloud_sql_state, "session_factory", Mock())

    orm.close_v1_engines()

    engine.dispose.assert_called_once_with()
    connector.close.assert_called_once_with()
    assert orm._cloud_sql_state.engine is None
    assert orm._cloud_sql_state.connector is None
    assert orm._cloud_sql_state.session_factory is None
