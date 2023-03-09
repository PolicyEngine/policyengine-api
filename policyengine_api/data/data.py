import sqlite3
from policyengine_api.constants import REPO, VERSION, COUNTRY_PACKAGE_VERSIONS
from policyengine_api.utils import hash_object
from pathlib import Path
import json
from google.cloud.sql.connector import Connector
from google.cloud.logging import Client
import sqlalchemy
import os


logging_client = Client()
logging_client.setup_logging()
logger = logging_client.logger("policyengine-api")


class PolicyEngineDatabase:
    """
    A wrapper around the database connection.

    It uses the Python package sqlite3.
    """

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
            if initialize and not Path(self.db_url).exists():
                self.initialize()
        else:
            self._create_pool()
            if initialize:
                self.initialize()

    def _create_pool(self):
        instance_connection_name = (
            "policyengine-api:us-central1:policyengine-api-data"
        )
        connector = Connector()
        db_user = "policyengine"
        db_pass = os.environ["POLICYENGINE_DB_PASSWORD"]
        if db_pass == ".dbpw":
            with open(".dbpw") as f:
                db_pass = f.read().strip()
        db_name = "policyengine"
        conn = connector.connect(
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

    def query(self, *query, retry: bool = False):
        if self.local:
            with sqlite3.connect(self.db_url) as conn:
                try:
                    try:
                        return conn.execute(*query)
                    except:
                        return conn.execute(query[0], query[1:])
                except sqlite3.IntegrityError as e:
                    pass
        else:
            try:
                with self.pool.connect() as conn:
                    try:
                        query = list(query)
                        main_query = query[0]
                        main_query = main_query.replace("?", "%s")
                        query[0] = main_query
                        return conn.execute(*query)
                    except sqlalchemy.exc.IntegrityError as e:
                        pass
            except Exception as e:
                if retry:
                    raise e
                else:
                    self._create_pool()
                    return self.query(*query, retry=True)

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

        # Insert the UK, US and Canadian 'current law' policies.

        try:
            self.set_in_table(
                "policy",
                dict(),
                dict(
                    id=1,
                    country_id="uk",
                    label="Current law",
                    api_version=COUNTRY_PACKAGE_VERSIONS["uk"],
                    policy_json=json.dumps({}),
                    policy_hash=hash_object({}),
                ),
            )
        except:
            pass

        try:
            self.set_in_table(
                "policy",
                dict(),
                dict(
                    id=2,
                    country_id="us",
                    label="Current law",
                    api_version=COUNTRY_PACKAGE_VERSIONS["us"],
                    policy_json=json.dumps({}),
                    policy_hash=hash_object({}),
                ),
            )
        except:
            pass

        try:
            self.set_in_table(
                "policy",
                dict(),
                dict(
                    id=3,
                    country_id="ca",
                    label="Current law",
                    api_version=COUNTRY_PACKAGE_VERSIONS["ca"],
                    policy_json=json.dumps({}),
                    policy_hash=hash_object({}),
                ),
            )
        except:
            pass

        try:
            self.set_in_table(
                "policy",
                dict(),
                dict(
                    id=4,
                    country_id="ng",
                    label="Current law",
                    api_version=COUNTRY_PACKAGE_VERSIONS["ng"],
                    policy_json=json.dumps({}),
                    policy_hash=hash_object({}),
                ),
            )
        except:
            pass

    def get_in_table(self, table_name: str, **kwargs):
        """
        Find a row in a table.

        Args:
            table_name (str): The name of the table.
            **kwargs: The column names and values to match.

        Returns:
            dict: The row.
        """
        if not self.local:
            # Needed in MySQL to cast JSON columns.
            for k, v in kwargs.items():
                if "json" in k:
                    kwargs[k] = f"CAST({v} AS JSON)"
        # Construct the query.
        query = f"SELECT * FROM {table_name} WHERE "
        query += " AND ".join([f"{k} = ?" for k in kwargs.keys()])
        # Execute the query.
        cursor = self.query(query, tuple(kwargs.values()))
        if cursor is None:
            return None
        result = cursor.fetchone()
        if result is None:
            return None
        # Return the result, as a dictionary with the column names as keys.
        if self.local:
            columns = [column[0] for column in cursor.description]
            return dict(zip(columns, result))
        else:
            return dict(result)

    def set_in_table(
        self,
        table_name: str,
        match: dict,
        update: dict,
        auto_increment: str = None,
    ):
        """
        Update a row in a table. If the row doesn't exist, create it.

        Args:
            table_name (str): The name of the table.
            **data: The column names and values to update.
        """
        selector = f"SELECT * FROM {table_name} WHERE " + " AND ".join(
            [f"{k} = ?" for k in match.keys()]
        )
        if len(match) > 0:
            selection = self.query(selector, tuple(match.values()))
        if len(match) == 0 or selection.fetchone() is None:
            # If auto_increment is set to the name of the ID column, then
            # increment the ID.
            if auto_increment is not None:
                # Get the maximum ID.
                max_id = self.query(
                    f"SELECT MAX({auto_increment}) FROM {table_name}"
                ).fetchone()[0]
                # If no rows exist, set the ID to 1.
                if max_id is None:
                    max_id = 0
                # Set the ID to the maximum ID plus 1.
                update[auto_increment] = max_id + 1
            full_entry = {**match, **update}
            insertor = (
                f"INSERT INTO {table_name} ("
                + ", ".join([f"{k}" for k in full_entry.keys()])
                + ") VALUES ("
                + ", ".join(["?" for k in full_entry.keys()])
                + ")"
            )
            try:
                # Test that the string formatting works.
                self.query(insertor, tuple(full_entry.values()))
            except sqlite3.IntegrityError as e:
                # Try increasing the ID.
                if auto_increment is not None:
                    self.set_in_table(
                        table_name, match, update, auto_increment
                    )
        else:
            # If there are multiple entries matching the selection, delete all but one.
            while len(selection.fetchall()) > 1:
                deleter = f"DELETE FROM {table_name} WHERE " + " AND ".join(
                    [f"{k} = ?" for k in match.keys()]
                )
                self.query(deleter, tuple(match.values()))
                selection = self.query(selector, tuple(match.values()))
            # Update the row.
            updater = (
                f"UPDATE {table_name} SET "
                + ", ".join([f"{k} = ?" for k in update.keys()])
                + " WHERE "
                + " AND ".join([f"{k} = ?" for k in match.keys()])
            )
            self.query(updater, tuple(update.values()) + tuple(match.values()))

    def set_policy_label(self, policy_id: int, country_id: str, label: str):
        """
        Set the label of a policy.

        Args:
            policy_id (int): The ID of the policy.
            country_id (str): The country ID.
            label (str): The new label.
        """
        # First, get the policy.
        policy = self.get_in_table(
            "policy", id=policy_id, country_id=country_id
        )
        # Update the label.
        policy["label"] = label
        # Update the policy.
        self.set_in_table(
            "policy",
            dict(id=policy_id, country_id=country_id),
            dict(
                label=label,
                policy_json=policy["policy_json"],
                policy_hash=policy["policy_hash"],
                api_version=policy["api_version"],
                country_id=policy["country_id"],
            ),
        )

    def delete_policy(self, policy_id: int, country_id: str):
        """
        Delete a policy.

        Args:
            policy_id (int): The ID of the policy.
            country_id (str): The country ID.
        """
        self.query(
            f"DELETE FROM policy WHERE id = ? AND country_id = ?",
            (policy_id, country_id),
        )


database = PolicyEngineDatabase(local=False, initialize=True)
