"""Canonical SQLAlchemy engine and Session configuration for API v1."""

from __future__ import annotations

import atexit
import fcntl
import json
import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from google.cloud.sql.connector import Connector, IPTypes
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS, REPO
from policyengine_api.utils import hash_object


load_dotenv()

DEFAULT_REMOTE_DB_INSTANCE_CONNECTION_NAME = (
    "policyengine-api:us-central1:policyengine-api-data"
)
DEFAULT_REMOTE_DB_USER = "policyengine"
DEFAULT_REMOTE_DB_NAME = "policyengine"
CLOUD_SQL_IP_TYPE = IPTypes.PUBLIC
DATABASE_POOL_RECYCLE_SECONDS = 1800
DATABASE_POOL_SIZE = 5
DATABASE_POOL_MAX_OVERFLOW = 2
DATABASE_POOL_TIMEOUT_SECONDS = 30
LOCAL_DATABASE_PATH = REPO / "policyengine_api" / "data" / "policyengine.db"

_v1_engines: dict[bool, Engine] = {}
_v1_session_factories: dict[bool, sessionmaker[Session]] = {}
_cloud_sql_connectors: dict[bool, Connector] = {}


def get_remote_database_config() -> dict[str, str]:
    return {
        "instance_connection_name": os.environ.get(
            "POLICYENGINE_DB_INSTANCE_CONNECTION_NAME",
            DEFAULT_REMOTE_DB_INSTANCE_CONNECTION_NAME,
        ),
        "db_user": os.environ.get("POLICYENGINE_DB_USER", DEFAULT_REMOTE_DB_USER),
        "db_name": os.environ.get("POLICYENGINE_DB_NAME", DEFAULT_REMOTE_DB_NAME),
    }


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return SQLAlchemy's standard configurable Session factory."""

    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


def _initialize_local_database(database_path: Path) -> None:
    initialization_sql = (
        REPO / "policyengine_api" / "data" / "initialise_local.sql"
    ).read_text(encoding="utf-8")
    with sqlite3.connect(database_path) as connection:
        connection.executescript(initialization_sql)
        connection.executemany(
            """
            INSERT INTO policy
                (id, country_id, label, api_version, policy_json, policy_hash)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    policy_id,
                    country_id,
                    "Current law",
                    COUNTRY_PACKAGE_VERSIONS[country_id],
                    json.dumps({}),
                    hash_object({}),
                )
                for policy_id, country_id in enumerate(
                    COUNTRY_PACKAGE_VERSIONS, start=1
                )
            ],
        )


# TODO: Remove this local-database initialization pattern and replace the local
# persistence path with a traditional cache. Application imports should
# eventually neither create a database file nor bootstrap a schema.
def _ensure_local_database(database_path: Path = LOCAL_DATABASE_PATH) -> None:
    lock_path = Path(f"{database_path}.init.lock")
    with lock_path.open("w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            if not database_path.exists():
                _initialize_local_database(database_path)
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def _build_local_engine() -> Engine:
    _ensure_local_database()
    return create_engine(f"sqlite+pysqlite:///{LOCAL_DATABASE_PATH}")


def _database_password() -> str:
    password = os.environ["POLICYENGINE_DB_PASSWORD"]
    if password == ".dbpw":
        return Path(".dbpw").read_text(encoding="utf-8").strip()
    return password


def _build_remote_engine() -> Engine:
    config = get_remote_database_config()
    connector = Connector(
        ip_type=CLOUD_SQL_IP_TYPE,
        refresh_strategy="LAZY",
    )
    password = _database_password()

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
    _cloud_sql_connectors[False] = connector
    return engine


def get_v1_engine(*, local: bool = False) -> Engine:
    """Return one process-owned SQLAlchemy Engine for the selected runtime."""

    use_local = local or os.environ.get("FLASK_DEBUG") == "1"
    if use_local not in _v1_engines:
        _v1_engines[use_local] = (
            _build_local_engine() if use_local else _build_remote_engine()
        )
    return _v1_engines[use_local]


def get_v1_session_factory(*, local: bool = False) -> sessionmaker[Session]:
    """Return one configured Session factory per process-owned v1 Engine."""

    if local not in _v1_session_factories:
        _v1_session_factories[local] = build_session_factory(get_v1_engine(local=local))
    return _v1_session_factories[local]


def clear_v1_session_factories() -> None:
    """Forget cached factories, primarily after replacing an Engine in tests."""

    _v1_session_factories.clear()


def close_v1_engines() -> None:
    """Release process-owned SQLAlchemy pools and Cloud SQL connectors."""

    clear_v1_session_factories()
    for engine in _v1_engines.values():
        engine.dispose()
    _v1_engines.clear()
    for connector in _cloud_sql_connectors.values():
        connector.close()
    _cloud_sql_connectors.clear()


atexit.register(close_v1_engines)
