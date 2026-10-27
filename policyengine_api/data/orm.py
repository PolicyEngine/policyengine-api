"""Canonical SQLAlchemy engine and Session configuration for API v1."""

from __future__ import annotations

import atexit
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from dotenv import load_dotenv
from google.cloud.sql.connector import Connector, IPTypes
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

if TYPE_CHECKING:
    from sqlalchemy.engine.interfaces import DBAPIConnection

load_dotenv()

DEFAULT_REMOTE_DB_USER = "policyengine"
DEFAULT_REMOTE_DB_NAME = "policyengine"
CLOUD_SQL_IP_TYPE = IPTypes.PUBLIC
DATABASE_POOL_RECYCLE_SECONDS = 1800
DATABASE_POOL_SIZE = 5
DATABASE_POOL_MAX_OVERFLOW = 2
DATABASE_POOL_TIMEOUT_SECONDS = 30
# MySQL's CLIENT_FOUND_ROWS capability flag (pymysql.constants.CLIENT.FOUND_ROWS).
# With it, an UPDATE reports the rows it matched rather than the rows whose
# values changed, which SQLAlchemy's MySQL dialects rely on to check UPDATE row
# counts. SQLAlchemy sets it only on connections it opens from a URL, not on
# those a creator= function opens. The value is written out because application
# code may not import database drivers (rule api.data.sqlalchemy-and-alembic-only).
MYSQL_CLIENT_FOUND_ROWS_FLAG = 2


@dataclass
class _CloudSqlState:
    """The process-owned Cloud SQL connector, engine and session factory.

    Each is created on first use and released by close_v1_engines.
    """

    connector: Connector | None = None
    engine: Engine | None = None
    session_factory: sessionmaker[Session] | None = None


_cloud_sql_state = _CloudSqlState()


def get_remote_database_config() -> dict[str, str]:
    """Read the Cloud SQL instance, user and database name from the environment.

    Raise KeyError when POLICYENGINE_DB_INSTANCE_CONNECTION_NAME is unset; the
    user and database name default to ``policyengine``.
    """
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
    config = get_remote_database_config()
    connector = Connector(
        ip_type=CLOUD_SQL_IP_TYPE,
        refresh_strategy="LAZY",
    )
    password = os.environ["POLICYENGINE_DB_PASSWORD"]

    def get_connection() -> DBAPIConnection:
        return connector.connect(
            instance_connection_string=config["instance_connection_name"],
            driver="pymysql",
            db=config["db_name"],
            user=config["db_user"],
            password=password,
            client_flag=MYSQL_CLIENT_FOUND_ROWS_FLAG,
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
    _cloud_sql_state.connector = connector
    return engine


def get_v1_engine() -> Engine:
    """Return the process-owned Cloud SQL engine; never select SQLite."""
    if _cloud_sql_state.engine is None:
        _cloud_sql_state.engine = _build_remote_engine()
    return _cloud_sql_state.engine


def get_v1_session_factory() -> sessionmaker[Session]:
    """Return one configured Session factory for the Cloud SQL engine."""
    if _cloud_sql_state.session_factory is None:
        _cloud_sql_state.session_factory = build_session_factory(get_v1_engine())
    return _cloud_sql_state.session_factory


def clear_v1_session_factories() -> None:
    """Forget cached factories, primarily after replacing an Engine in tests."""
    _cloud_sql_state.session_factory = None


def close_v1_engines() -> None:
    """Release process-owned SQLAlchemy pools and Cloud SQL connectors."""
    clear_v1_session_factories()
    if _cloud_sql_state.engine is not None:
        _cloud_sql_state.engine.dispose()
        _cloud_sql_state.engine = None
    if _cloud_sql_state.connector is not None:
        _cloud_sql_state.connector.close()
        _cloud_sql_state.connector = None


atexit.register(close_v1_engines)
