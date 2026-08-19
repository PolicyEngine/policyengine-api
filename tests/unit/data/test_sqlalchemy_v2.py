from unittest.mock import Mock

import sqlalchemy
from pathlib import Path

import policyengine_api.data.orm as orm


def test_sqlalchemy_v2_or_newer_is_installed():
    assert int(sqlalchemy.__version__.split(".")[0]) >= 2


def test_remote_engine_delegates_connections_and_pooling_to_sqlalchemy(monkeypatch):
    connector_calls = []
    engine_calls = []

    class FakeConnector:
        def __init__(self, **options):
            self.options = options

        def connect(self, **options):
            connector_calls.append(options)
            return object()

        def close(self):
            pass

    connector = FakeConnector()

    def connector_factory(**options):
        connector.options = options
        return connector

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

    assert engine == "engine"
    assert connector.options == {
        "ip_type": orm.IPTypes.PUBLIC,
        "refresh_strategy": "LAZY",
    }
    url, options = engine_calls[0]
    assert url == "mysql+pymysql://"
    assert options["pool_pre_ping"] is True
    assert options["pool_recycle"] == 1800
    assert options["pool_size"] == 5
    assert options["max_overflow"] == 2
    assert options["pool_timeout"] == 30
    assert connector_calls == []
    options["creator"]()
    assert connector_calls == [
        {
            "instance_connection_string": "project:region:instance",
            "driver": "pymysql",
            "db": "database",
            "user": "user",
            "password": "password",
        }
    ]


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
    monkeypatch.setattr(orm, "_v1_engine", engine)
    monkeypatch.setattr(orm, "_cloud_sql_connector", connector)
    monkeypatch.setattr(orm, "_v1_session_factory", Mock())

    orm.close_v1_engines()

    engine.dispose.assert_called_once_with()
    connector.close.assert_called_once_with()
    assert orm._v1_engine is None
    assert orm._cloud_sql_connector is None
    assert orm._v1_session_factory is None
