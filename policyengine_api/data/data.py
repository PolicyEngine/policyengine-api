import sqlite3
from policyengine_api.constants import REPO, VERSION
from policyengine_api.utils import hash_object
from pathlib import Path
import json


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
        if local:
            # Local development uses a sqlite database.
            self.db_url = (
                REPO / "policyengine_api" / "data" / "policyengine.db"
            )
            if initialize:
                self.initialize()

    def query(self, *query):
        with sqlite3.connect(self.db_url) as conn:
            try:
                return conn.execute(*query)
            except Exception as e:
                print(f"Error executing query: {query}")
                raise

    def initialize(self):
        """
        Create the database tables.
        """
        # If the db_url exists, delete it.
        if Path(self.db_url).exists():
            Path(self.db_url).unlink()
        # If the db_url doesn't exist, create it.
        if not Path(self.db_url).exists():
            Path(self.db_url).touch()

        with open(
            REPO / "policyengine_api" / "data" / "initialise.sql", "r"
        ) as f:
            full_query = f.read()
            # Split the query into individual queries.
            queries = full_query.split(";")
            for query in queries:
                # Execute each query.
                self.query(query)
        
        # Insert the UK and US 'current law' policies.

        self.update_in_table(
            "policy",
            dict(id=1),
            dict(country_id="uk", label="Current law", api_version=VERSION, policy_json="{}", policy_hash=hash_object({})),
        )

        self.update_in_table(
            "policy",
            dict(id=1),
            dict(country_id="us", label="Current law", api_version=VERSION, policy_json="{}", policy_hash=hash_object({})),
        )

    def get_in_table(self, table_name: str, **kwargs):
        """
        Find a row in a table.

        Args:
            table_name (str): The name of the table.
            **kwargs: The column names and values to match.

        Returns:
            dict: The row.
        """
        # Construct the query.
        query = f"SELECT * FROM {table_name} WHERE "
        query += " AND ".join([f"{k} = ?" for k in kwargs.keys()])
        # Execute the query.
        result = self.query(query, tuple(kwargs.values()))
        # Return the result.
        return result.fetchone()
    
    def update_in_table(self, table_name: str, match: dict, update: dict):
        """
        Update a row in a table. If the row doesn't exist, create it.

        Args:
            table_name (str): The name of the table.
            **data: The column names and values to update.
        """
        # Construct the query.
        query = f"UPDATE {table_name} SET "
        query += ", ".join([f"{k} = ?" for k in update.keys()])
        query += " WHERE "
        query += " AND ".join([f"{k} = ?" for k in match.keys()])
        # Execute the query.
        self.query(
            query,
            tuple(update.values()) + tuple(match.values()),
        )
    