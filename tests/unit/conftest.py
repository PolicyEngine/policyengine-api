import pytest
import sqlite3
from policyengine_api.data import PolicyEngineDatabase
from policyengine_api.constants import REPO


class TestPolicyEngineDatabase(PolicyEngineDatabase):
    """Test version of PolicyEngineDatabase that uses in-memory SQLite"""

    def __init__(self, initialize: bool = True):
        self.local = True  # Always use SQLite for tests
        if initialize:
            self._setup_connection()
            self.initialize()

    def _setup_connection(self):
        """Setup the in-memory connection"""
        if not hasattr(self, "_connection"):
            self._connection = sqlite3.connect(":memory:")

            def dict_factory(cursor, row):
                d = {}
                for idx, col in enumerate(cursor.description):
                    d[col[0]] = row[idx]
                return d

            self._connection.row_factory = dict_factory

    def initialize(self):
        """
        Override initialize to avoid file operations from parent class
        """
        self._setup_connection()

        # Read the SQL initialization file
        init_file = (
            REPO
            / "policyengine_api"
            / "data"
            / f"initialise{'_local' if self.local else ''}.sql"
        )
        with open(init_file, "r") as f:
            full_query = f.read()

        # Split and execute the queries
        queries = full_query.split(";")
        for query in queries:
            if query.strip():  # Skip empty queries
                self.query(query)

    def query(self, *query):
        """Override query method to use in-memory connection"""
        if not hasattr(self, "_connection"):
            # Create a persistent connection for the in-memory database
            self._connection = sqlite3.connect(self.db_url)

            def dict_factory(cursor, row):
                d = {}
                for idx, col in enumerate(cursor.description):
                    d[col[0]] = row[idx]
                return d

            self._connection.row_factory = dict_factory

        cursor = self._connection.cursor()
        result = cursor.execute(*query)
        self._connection.commit()
        return result

    def clean(self):
        """Clear all data from tables while preserving the schema"""
        if hasattr(self, "_connection"):
            cursor = self._connection.cursor()

            # Get all table names
            tables = cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()

            # Disable foreign key checks temporarily
            cursor.execute("PRAGMA foreign_keys=OFF")

            # Delete all data from each table
            for table in tables:
                table_name = table["name"]
                cursor.execute(f"DELETE FROM {table_name}")

            # Re-enable foreign key checks
            cursor.execute("PRAGMA foreign_keys=ON")

            self._connection.commit()


@pytest.fixture(scope="session")
def test_db():
    """Create a test database instance that persists for the whole test session"""
    db = TestPolicyEngineDatabase(initialize=True)
    yield db
    # Clean up the connection when done
    if hasattr(db, "_connection"):
        db._connection.close()


@pytest.fixture(autouse=True)
def override_database(test_db, monkeypatch):
    """
    Global database override that affects all imports of the database.
    This fixture automatically applies to all tests.
    """
    test_db.clean()

    # Patch at the root module level where database is defined
    import policyengine_api.data

    monkeypatch.setattr(policyengine_api.data, "database", test_db)

    # Also patch the module-level variable for any existing imports
    import sys

    for module_name, module in list(sys.modules.items()):
        if module_name.startswith("policyengine_api."):
            if hasattr(module, "database"):
                monkeypatch.setattr(module, "database", test_db)

    yield test_db
