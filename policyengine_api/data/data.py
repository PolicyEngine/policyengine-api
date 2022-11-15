import sqlite3
from policyengine_api.repo import REPO
from pathlib import Path

class PolicyEngineDatabase:
    """
    A wrapper around the database connection. 

    It uses the Python package sqlite3.
    """

    def __init__(self, db_url: str = REPO / "policyengine_api" / "data" / "policyengine.db"):
        self.db_url = db_url
        self.connection = sqlite3.connect(self.db_url)
        self.initialize()

    def query(self, *query):
        return self.connection.execute(*query)

    def initialize(self):
        """
        Create the database tables. 
        """
        # If the db_url doesn't exist, create it.
        if not Path(self.db_url).exists():
            Path(self.db_url).touch()

        with open(REPO / "policyengine_api" / "data" / "initialise.sql", "r") as f:
            full_query = f.read()
            # Split the query into individual queries.
            queries = full_query.split(";")
            for query in queries:
                # Execute each query.
                self.query(query)