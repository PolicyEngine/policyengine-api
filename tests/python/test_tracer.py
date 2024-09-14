import pytest
import json
from policyengine_api.data import local_database
from policyengine_api.endpoints.tracer import get_tracer
from flask import Response

class TestTracer:
    # Set shared variables
    country_id = "us"
    household_id = 1
    policy_id = 1
    api_version = "1.0.0"
    variable_name = "household_net_income"
    tracer_output = {
        "name": "household_net_income",
        "value": 50000,
        "formula": "earnings + capital_income + benefits - taxes",
        "dependencies": [
            {"name": "earnings", "value": 45000},
            {"name": "capital_income", "value": 5000},
            {"name": "benefits", "value": 2000},
            {"name": "taxes", "value": 2000}
        ]
    }

    @pytest.fixture(autouse=True)
    def setup_and_teardown(self):
        # Setup
        local_database.query(
            """
            INSERT INTO tracers 
            (household_id, policy_id, country_id, api_version, tracer_output, variable_name)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                self.household_id,
                self.policy_id,
                self.country_id,
                self.api_version,
                json.dumps(self.tracer_output),
                self.variable_name,
            ),
        )
        local_database.commit()
        
        yield
        
        # Teardown
        local_database.query(
            "DELETE FROM tracers WHERE household_id = ? AND policy_id = ?",
            (self.household_id, self.policy_id),
        )
        local_database.commit()

    def test_get_tracer(self):
        result = get_tracer(
            self.country_id,
            self.household_id,
            self.api_version,
            self.variable_name,
            self.policy_id,
        )

        assert isinstance(result, dict)
        assert result["status"] == 200
        assert result["result"]["household_id"] == self.household_id
        assert result["result"]["policy_id"] == self.policy_id
        assert result["result"]["country_id"] == self.country_id
        assert result["result"]["api_version"] == self.api_version
        assert result["result"]["variable_name"] == self.variable_name
        assert result["result"]["tracer_output"] == self.tracer_output

    def test_get_tracer_not_found(self):
        result = get_tracer(
            self.country_id,
            999,  # Non-existent household_id
            self.api_version,
            self.variable_name,
            self.policy_id,
        )

        assert isinstance(result, Response)
        assert result.status_code == 404
        response_body = json.loads(result.get_data(as_text=True))
        assert response_body["status"] == "error"
        assert "Tracer not found" in response_body["message"]
