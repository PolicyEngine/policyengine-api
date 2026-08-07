import atexit
import fcntl
import sqlite3
from policyengine_api.constants import REPO, COUNTRY_PACKAGE_VERSIONS
from policyengine_api.utils import hash_object
from pathlib import Path
from dotenv import load_dotenv
import json
from google.cloud.sql.connector import Connector, IPTypes
import sqlalchemy
import os
import sys

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


def get_remote_database_config() -> dict[str, str]:
    return {
        "instance_connection_name": os.environ.get(
            "POLICYENGINE_DB_INSTANCE_CONNECTION_NAME",
            DEFAULT_REMOTE_DB_INSTANCE_CONNECTION_NAME,
        ),
        "db_user": os.environ.get("POLICYENGINE_DB_USER", DEFAULT_REMOTE_DB_USER),
        "db_name": os.environ.get("POLICYENGINE_DB_NAME", DEFAULT_REMOTE_DB_NAME),
    }


class _ResultProxy:
    """Lightweight wrapper that eagerly fetches results from a
    SQLAlchemy CursorResult so they survive connection closure.
    Provides fetchone()/fetchall() with dict-like row access."""

    def __init__(self, cursor_result):
        try:
            # Use .mappings() so rows behave like dicts
            self._rows = list(cursor_result.mappings())
        except Exception:
            # For non-SELECT statements (INSERT/UPDATE/DELETE)
            # there are no rows to fetch
            self._rows = []
        self._index = 0

    def fetchone(self):
        if self._index < len(self._rows):
            row = self._rows[self._index]
            self._index += 1
            return row
        return None

    def fetchall(self):
        remaining = self._rows[self._index :]
        self._index = len(self._rows)
        return remaining


class _TransactionProxy:
    """Execute queries against an existing connection inside a transaction."""

    def __init__(self, connection, local: bool):
        self._connection = connection
        self._local = local

    def query(self, *query):
        if self._local:
            cursor = self._connection.cursor()
            return cursor.execute(*query)

        query = list(query)
        main_query = query[0].replace("?", "%s")
        query[0] = main_query
        params = query[1] if len(query) > 1 else None
        if params is not None:
            result = self._connection.exec_driver_sql(main_query, params)
        else:
            result = self._connection.exec_driver_sql(main_query)
        return _ResultProxy(result)


class PolicyEngineDatabase:
    """
    A wrapper around the database connection.

    It uses the Python package sqlite3.
    """

    household_cache: dict = {}

    @staticmethod
    def _dict_factory(cursor, row):
        d = {}
        for idx, col in enumerate(cursor.description):
            d[col[0]] = row[idx]
        return d

    def __init__(
        self,
        local: bool = False,
        initialize: bool = False,
    ):
        self.local = local
        self._closed = False
        if local:
            # Local development uses a sqlite database.
            self.db_url = REPO / "policyengine_api" / "data" / "policyengine.db"
            # Serialize the exists-check + initialize under an exclusive file
            # lock: with multiple gunicorn workers importing concurrently on a
            # fresh instance, both can otherwise pass the exists() check and
            # race initialize() (seed INSERTs collide -> worker dies at boot),
            # or one can observe a created-but-unseeded file and skip
            # initialization entirely.
            lock_path = str(self.db_url) + ".init.lock"
            with open(lock_path, "w") as lock_file:
                fcntl.flock(lock_file, fcntl.LOCK_EX)
                try:
                    if initialize or not Path(self.db_url).exists():
                        self.initialize()
                finally:
                    fcntl.flock(lock_file, fcntl.LOCK_UN)
        else:
            self._create_pool()
            if initialize:
                self.initialize()

    def _create_pool(self):
        db_config = get_remote_database_config()
        self.connector = Connector(
            ip_type=CLOUD_SQL_IP_TYPE,
            refresh_strategy="LAZY",
        )
        db_pass = os.environ["POLICYENGINE_DB_PASSWORD"]
        if db_pass == ".dbpw":
            with open(".dbpw") as f:
                db_pass = f.read().strip()

        def getconn():
            return self.connector.connect(
                instance_connection_string=db_config["instance_connection_name"],
                driver="pymysql",
                db=db_config["db_name"],
                user=db_config["db_user"],
                password=db_pass,
            )

        self.pool = sqlalchemy.create_engine(
            "mysql+pymysql://",
            creator=getconn,
            pool_pre_ping=True,
            pool_recycle=DATABASE_POOL_RECYCLE_SECONDS,
            pool_size=DATABASE_POOL_SIZE,
            max_overflow=DATABASE_POOL_MAX_OVERFLOW,
            pool_timeout=DATABASE_POOL_TIMEOUT_SECONDS,
        )

    def close(self) -> None:
        """Release process-owned database and connector resources."""

        if getattr(self, "_closed", False):
            return
        if self.local:
            connection = getattr(self, "_connection", None)
            if connection is not None:
                connection.close()
            self._closed = True
            return

        try:
            self.pool.dispose()
        finally:
            self.connector.close()
            self._closed = True

    def _close_pool(self):
        """Backward-compatible alias for callers predating ``close``."""

        self.close()

    def _execute_remote(self, query_args):
        """Execute a query against the remote database using
        SQLAlchemy v2 connection-based execution."""
        main_query = query_args[0]
        params = query_args[1] if len(query_args) > 1 else None
        with self.pool.begin() as conn:
            if params is not None:
                result = conn.exec_driver_sql(main_query, params)
            else:
                result = conn.exec_driver_sql(main_query)
            # Return a lightweight wrapper that holds
            # the fetched results so they survive the
            # connection context closing
            return _ResultProxy(result)

    def _execute_remote_transaction(self, callback):
        with self.pool.begin() as conn:
            proxy = _TransactionProxy(conn, local=False)
            return callback(proxy)

    def query(self, *query):
        if self.local:
            with sqlite3.connect(self.db_url) as conn:
                conn.row_factory = self._dict_factory
                cursor = conn.cursor()
                return cursor.execute(*query)
        else:
            query = list(query)
            main_query = query[0]
            main_query = main_query.replace("?", "%s")
            query[0] = main_query
            return self._execute_remote(query)

    def transaction(self, callback):
        if self.local:
            connection = getattr(self, "_connection", None)
            owns_connection = connection is None
            if owns_connection:
                connection = sqlite3.connect(self.db_url)
            connection.row_factory = self._dict_factory
            try:
                connection.execute("BEGIN IMMEDIATE")
                proxy = _TransactionProxy(connection, local=True)
                result = callback(proxy)
                connection.commit()
                return result
            except Exception:
                connection.rollback()
                raise
            finally:
                if owns_connection:
                    connection.close()

        return self._execute_remote_transaction(callback)

    def initialize(self):
        """
        Create the database tables.
        """
        if self.local:
            # If the db_url exists, delete it.
            if Path(self.db_url).exists():
                Path(self.db_url).unlink()
            # If the db_url doesn't exist, create it.
            if not Path(self.db_url).exists():
                Path(self.db_url).touch()

        with open(
            REPO
            / "policyengine_api"
            / "data"
            / f"initialise{'_local' if self.local else ''}.sql",
            "r",
        ) as f:
            full_query = f.read()
            # Split the query into individual queries.
            queries = full_query.split(";")
            for query in queries:
                print(query, sys.stdout)
                # Execute each query.
                self.query(query)

        # Insert the UK, US and Canadian 'current law' policies. e.g. the UK policy table must have a row with id=1, country_id="uk", label="Current law", api_version=COUNTRY_PACKAGE_VERSIONS["uk"], policy_json="{}", policy_hash=hash_object({})
        for country_id, policy_id in zip(
            COUNTRY_PACKAGE_VERSIONS.keys(),
            range(1, 1 + len(COUNTRY_PACKAGE_VERSIONS)),
        ):
            self.query(
                "INSERT INTO policy (id, country_id, label, api_version, policy_json, policy_hash) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    policy_id,
                    country_id,
                    "Current law",
                    COUNTRY_PACKAGE_VERSIONS[country_id],
                    json.dumps({}),
                    hash_object({}),
                ),
            )


# Determine if app is in debug mode, and if so, do not attempt connection with remote db
if os.environ.get("FLASK_DEBUG") == "1":
    database = PolicyEngineDatabase(local=True, initialize=False)
else:
    database = PolicyEngineDatabase(local=False, initialize=False)

# TODO: Remove this eager SQLite-backed local database initialization and
# replace it with a traditional cache so importing the application does not
# create files or perform schema setup.
local_database = PolicyEngineDatabase(local=True, initialize=False)


def close_runtime_databases() -> None:
    """Close database resources owned by the current application process."""

    try:
        database.close()
    finally:
        if local_database is not database:
            local_database.close()


atexit.register(close_runtime_databases)
