import pytest

valid_simulation_data = {
    "country_id": "us",
    "api_version": "1.0.0",
    "population_id": "household_test_123",
    "population_type": "household",
    "policy_id": 1,
}

duplicate_simulation_data = {
    "country_id": "us",
    "api_version": "1.0.0",
    "population_id": "household_test_123",
    "population_type": "household",
    "policy_id": 1,
}


@pytest.fixture
def existing_simulation_record(test_db):
    """Insert an existing simulation record into the database."""
    test_db.query(
        """INSERT INTO simulation 
        (country_id, api_version, population_id, population_type, policy_id) 
        VALUES (?, ?, ?, ?, ?)""",
        (
            valid_simulation_data["country_id"],
            valid_simulation_data["api_version"],
            valid_simulation_data["population_id"],
            valid_simulation_data["population_type"],
            valid_simulation_data["policy_id"],
        ),
    )

    # Get the inserted record
    inserted_row = test_db.query(
        """SELECT * FROM simulation 
        WHERE country_id = ? AND api_version = ? 
        AND population_id = ? AND population_type = ? 
        AND policy_id = ?""",
        (
            valid_simulation_data["country_id"],
            valid_simulation_data["api_version"],
            valid_simulation_data["population_id"],
            valid_simulation_data["population_type"],
            valid_simulation_data["policy_id"],
        ),
    ).fetchone()

    return inserted_row