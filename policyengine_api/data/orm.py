"""Canonical SQLAlchemy engine and Session configuration for API v1."""

from __future__ import annotations

import atexit
import os

from dotenv import load_dotenv
from google.cloud.sql.connector import Connector, IPTypes
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

load_dotenv()

DEFAULT_REMOTE_DB_USER = "policyengine"
DEFAULT_REMOTE_DB_NAME = "policyengine"
CLOUD_SQL_IP_TYPE = IPTypes.PUBLIC
DATABASE_POOL_RECYCLE_SECONDS = 1800
DATABASE_POOL_SIZE = 5
DATABASE_POOL_MAX_OVERFLOW = 2
DATABASE_POOL_TIMEOUT_SECONDS = 30
_v1_engine: Engine | None = None
_v1_session_factory: sessionmaker[Session] | None = None
_cloud_sql_connector: Connector | None = None


def get_remote_database_config() -> dict[str, str]:
    return {
        "instance_connection_name": os.environ[
            "POLICYENGINE_DB_INSTANCE_CONNECTION_NAME"
        ],
        "db_user": os.environ.get("POLICYENGINE_DB_USER", DEFAULT_REMOTE_DB_USER),
        "db_name": os.environ.get("POLICYENGINE_DB_NAME", DEFAULT_REMOTE_DB_NAME),
    }


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return SQLAlchemy's standard configurable Session factory."""

    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


def _build_remote_engine() -> Engine:
    global _cloud_sql_connector
    config = get_remote_database_config()
    connector = Connector(
        ip_type=CLOUD_SQL_IP_TYPE,
        refresh_strategy="LAZY",
    )
    password = os.environ["POLICYENGINE_DB_PASSWORD"]

    def get_connection():
        return connector.connect(
            instance_connection_string=config["instance_connection_name"],
            driver="pymysql",
            db=config["db_name"],
            user=config["db_user"],
            password=password,
        )

    engine = create_engine(
        "mysql+pymysql://",
        creator=get_connection,
        pool_pre_ping=True,
        pool_recycle=DATABASE_POOL_RECYCLE_SECONDS,
        pool_size=DATABASE_POOL_SIZE,
        max_overflow=DATABASE_POOL_MAX_OVERFLOW,
        pool_timeout=DATABASE_POOL_TIMEOUT_SECONDS,
    )
    _cloud_sql_connector = connector
    return engine


def get_v1_engine() -> Engine:
    """Return the process-owned Cloud SQL engine; never select SQLite."""

    global _v1_engine
    if _v1_engine is None:
        _v1_engine = _build_remote_engine()
    return _v1_engine


def get_v1_session_factory() -> sessionmaker[Session]:
    """Return one configured Session factory for the Cloud SQL engine."""

    global _v1_session_factory
    if _v1_session_factory is None:
        _v1_session_factory = build_session_factory(get_v1_engine())
    return _v1_session_factory


def clear_v1_session_factories() -> None:
    """Forget cached factories, primarily after replacing an Engine in tests."""

    global _v1_session_factory
    _v1_session_factory = None


def close_v1_engines() -> None:
    """Release process-owned SQLAlchemy pools and Cloud SQL connectors."""

    global _cloud_sql_connector, _v1_engine
    clear_v1_session_factories()
    if _v1_engine is not None:
        _v1_engine.dispose()
        _v1_engine = None
    if _cloud_sql_connector is not None:
        _cloud_sql_connector.close()
        _cloud_sql_connector = None


atexit.register(close_v1_engines)
