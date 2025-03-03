import pytest
import json
from policyengine_api.services.tracer_analysis_service import (
    TracerAnalysisService,
)

valid_request_body = {
    "tracer_output": [
        "only_government_benefit <1500>",
        "    market_income <1000>",
        "        employment_income <1000>",
        "            main_employment_income <1000>",
        "    non_market_income <500>",
        "        pension_income <500>",
    ]
}

valid_tracer_row = {
    "household_id": "71424",
    "policy_id": "2",
    "country_id": "us",
    "api_version": "1.150.0",
    "tracer_output": json.dumps(valid_request_body["tracer_output"]),
}


@pytest.fixture
def tracer_service():
    """Fixture to initialize the TracerAnalysisService."""
    return TracerAnalysisService()


@pytest.fixture
def test_tracer_data(test_db):

    # Insert data using query()
    test_db.query(
        """
        INSERT INTO tracers (household_id, policy_id, country_id, api_version, tracer_output) 
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            valid_tracer_row["household_id"],
            valid_tracer_row["policy_id"],
            valid_tracer_row["country_id"],
            valid_tracer_row["api_version"],
            valid_tracer_row["tracer_output"],
        ),
    )

    # Verify that the data has been inserted
    inserted_row = test_db.query(
        "SELECT * FROM tracers WHERE household_id = ? AND policy_id = ? AND country_id = ? AND api_version = ?",
        (
            valid_tracer_row["household_id"],
            valid_tracer_row["policy_id"],
            valid_tracer_row["country_id"],
            valid_tracer_row["api_version"],
        ),
    ).fetchone()

    return inserted_row
