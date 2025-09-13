import pytest
import json

valid_report_data = {
    "country_id": "us",
    "simulation_1_id": 1,
    "simulation_2_id": None,
    "api_version": "1.0.0",
    "status": "pending",
    "output": None,
    "error_message": None,
}

sample_report_output = {
    "population_impact": {
        "baseline": {"decile_1": 1000},
        "reform": {"decile_1": 1100},
    },
    "budget_impact": 5000000,
}


@pytest.fixture
def existing_report_record(test_db):
    """Insert an existing report output record into the database."""
    test_db.query(
        """INSERT INTO report_outputs
        (country_id, simulation_1_id, simulation_2_id, api_version, status)
        VALUES (?, ?, ?, ?, ?)""",
        (
            valid_report_data["country_id"],
            valid_report_data["simulation_1_id"],
            valid_report_data["simulation_2_id"],
            valid_report_data["api_version"],
            valid_report_data["status"],
        ),
    )

    # Get the inserted record
    inserted_row = test_db.query(
        """SELECT * FROM report_outputs
        WHERE country_id = ? AND simulation_1_id = ? AND status = ?
        ORDER BY id DESC LIMIT 1""",
        (
            valid_report_data["country_id"],
            valid_report_data["simulation_1_id"],
            valid_report_data["status"],
        ),
    ).fetchone()

    return inserted_row
