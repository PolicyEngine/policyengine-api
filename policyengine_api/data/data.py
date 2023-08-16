import sqlite3
from policyengine_api.constants import REPO, VERSION, COUNTRY_PACKAGE_VERSIONS
from policyengine_api.utils import hash_object
from pathlib import Path
import json
from google.cloud.sql.connector import Connector
import sqlalchemy
import sqlalchemy.exc
import os
import sys


class PolicyEngineDatabase:
    """
    A wrapper around the database connection.

    It uses the Python package sqlite3.
    """

    household_cache: dict = {}

    def __init__(
        self,
        local: bool = False,
        initialize: bool = False,
    ):
        self.local = local
        if local:
            # Local development uses a sqlite database.
            self.db_url = (
                REPO / "policyengine_api" / "data" / "policyengine.db"
            )
            if initialize or not Path(self.db_url).exists():
                self.initialize()
        else:
            self._create_pool()
            if initialize:
                self.initialize()

        self.seed()

    def _create_pool(self):
        instance_connection_name = (
            "policyengine-api:us-central1:policyengine-api-data"
        )
        self.connector = Connector()
        db_user = "policyengine"
        db_pass = os.environ["POLICYENGINE_DB_PASSWORD"]
        if db_pass == ".dbpw":
            with open(".dbpw") as f:
                db_pass = f.read().strip()
        db_name = "policyengine"
        conn = self.connector.connect(
            instance_connection_string=instance_connection_name,
            driver="pymysql",
            db=db_name,
            user=db_user,
            password=db_pass,
        )
        self.pool = sqlalchemy.create_engine(
            "mysql+pymysql://",
            creator=lambda: conn,
        )

    def _close_pool(self):
        try:
            self.pool.dispose()
            self.connector.close()
        except:
            pass

    def query(self, *query):
        if self.local:
            with sqlite3.connect(self.db_url) as conn:

                def dict_factory(cursor, row):
                    d = {}
                    for idx, col in enumerate(cursor.description):
                        d[col[0]] = row[idx]
                    return d

                conn.row_factory = dict_factory
                cursor = conn.cursor()
                return cursor.execute(*query)
        else:
            query = list(query)
            main_query = query[0]
            main_query = main_query.replace("?", "%s")
            query[0] = main_query
            try:
                return self.pool.execute(*query)
            # Except InterfaceError and OperationalError, which are thrown when the connection is lost.
            except (
                sqlalchemy.exc.InterfaceError,
                sqlalchemy.exc.OperationalError,
            ) as e:
                try:
                    self._close_pool()
                    self._create_pool()
                    return self.pool.execute(*query)
                except Exception as e:
                    raise e

    def seed(self):
        """
        Pre-seed the database with records in the relevant folder
        """

        folder = REPO / "policyengine_api" / "data" / "seed"

        # Recursively loop through all SQL scripts in folder
        for dirpath, dirnames, filenames in os.walk(folder):
            for filename in filenames:
                full_filepath = os.path.join(dirpath, filename)
                with open(full_filepath, "r") as file:
                    try:
                        full_query = file.read()
                        queries = full_query.split(";")
                        for query in queries:
                            self.query(query)

                    except Exception as e:
                        print(
                            f"Error while seeding database with record {filename}: {e}",
                            file=sys.stdout,
                        )

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
                # Execute each query.
                self.query(query)

        # Insert the UK, US and Canadian 'current law' policies. e.g. the UK policy table must have a row with id=1, country_id="uk", label="Current law", api_version=COUNTRY_PACKAGE_VERSIONS["uk"], policy_json="{}", policy_hash=hash_object({})
        for country_id, policy_id in zip(
            COUNTRY_PACKAGE_VERSIONS.keys(),
            range(1, 1 + len(COUNTRY_PACKAGE_VERSIONS)),
        ):
            self.query(
                f"INSERT INTO policy (id, country_id, label, api_version, policy_json, policy_hash) VALUES (?, ?, ?, ?, ?, ?)",
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

local_database = PolicyEngineDatabase(local=True, initialize=False)
