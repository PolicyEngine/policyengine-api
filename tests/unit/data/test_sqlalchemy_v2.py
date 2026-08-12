from unittest.mock import Mock

import sqlalchemy
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.orm import Session

import policyengine_api.data.orm as orm
from policyengine_api.data.v1_models import Policy


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


def test_database_password_can_be_loaded_from_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("POLICYENGINE_DB_PASSWORD", ".dbpw")
    (tmp_path / ".dbpw").write_text("file-password\n", encoding="utf-8")

    assert orm._database_password() == "file-password"


def test_local_schema_preserves_the_documented_sqlite_policy_key_exception():
    from policyengine_api.data.local_database import create_local_v1_schema

    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        create_local_v1_schema(engine)

        policy_key = inspect(engine).get_pk_constraint("policy")
        assert policy_key["constrained_columns"] == ["id"]
        assert "tracers" in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_local_initializer_bootstraps_schema_and_current_law_rows(tmp_path):
    database_path = tmp_path / "local.db"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")

    try:
        orm._initialize_local_database(engine)
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(Policy)) > 0
            assert session.scalars(select(Policy)).first().policy_json == {}
    finally:
        engine.dispose()


def test_local_initializer_is_idempotent(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'local.db'}")
    try:
        orm._initialize_local_database(engine)
        orm._initialize_local_database(engine)

        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(Policy)) == len(
                orm.COUNTRY_PACKAGE_VERSIONS
            )
    finally:
        engine.dispose()


def test_close_v1_engines_disposes_pools_and_connectors(monkeypatch):
    engine = Mock()
    connector = Mock()
    monkeypatch.setattr(orm, "_v1_engines", {False: engine})
    monkeypatch.setattr(orm, "_cloud_sql_connectors", {False: connector})
    monkeypatch.setattr(orm, "_v1_session_factories", {False: Mock()})

    orm.close_v1_engines()

    engine.dispose.assert_called_once_with()
    connector.close.assert_called_once_with()
    assert orm._v1_engines == {}
    assert orm._cloud_sql_connectors == {}
    assert orm._v1_session_factories == {}
