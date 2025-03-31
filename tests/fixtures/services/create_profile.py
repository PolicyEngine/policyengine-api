import pytest
from tests.unit.conftest import TestPolicyEngineDatabase
from policyengine_api.data import PolicyEngineDatabase


@pytest.fixture(scope="session")
def test_db():
    """Create a test database instance that persists for the whole test session"""
    db = TestPolicyEngineDatabase(initialize=True)
    yield db
    if hasattr(db, "_connection"):
        db._connection.close()


@pytest.fixture
def fetch_created_record(test_db):
    """Returns a function to fetch a created user profile record by auth0_id"""

    def _fetch(auth0_id):
        with test_db._connection.cursor() as cursor:  # Ensure we're using a valid DB method
            cursor.execute(
                "SELECT * FROM user_profiles WHERE auth_id = ?", (auth0_id,)
            )
            result = cursor.fetchone()
        return result

    return _fetch  # ✅ Return the function itself
